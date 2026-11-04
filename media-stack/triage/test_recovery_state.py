"""Synthetic state recovery and import acknowledgement checks."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('triage_recovery_tests', Path(__file__).with_name('triage.py'))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

class RecoveryStateTests(unittest.TestCase):
    def setUp(self):
        self.p = t.Pipeline.__new__(t.Pipeline)
        self.p.db = sqlite3.connect(':memory:')
        self.addCleanup(self.p.db.close)
        self.p.db.execute('CREATE TABLE items (hash TEXT PRIMARY KEY,status TEXT,details TEXT,updated TEXT)')
        self.p.db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY,hash TEXT,previous_status TEXT,status TEXT,previous_details TEXT,details TEXT,at TEXT)')
        self.p.config = {'sonarr': {'url': 'http://organizer', 'api_key': 'synthetic'}}
        self.p.arr = Mock()
        self.p.tag = Mock()
        self.key = 'b' * 40

    def test_history_preserves_failure(self):
        self.p.record(self.key, 'erro', {'reason': 'old timeout'})
        self.p.record(self.key, 'reanalise-agendada', {'name': 'synthetic'})
        old,new,details = self.p.db.execute('SELECT previous_status,status,previous_details FROM events ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual((old,new), ('erro','reanalise-agendada'))
        self.assertEqual(json.loads(details)['reason'], 'old timeout')

    def test_superseded_never_scans_or_approves(self):
        self.p.record(self.key, 'substituido', {'replacement_hashes':['c'*40]})
        self.p.qget = Mock()
        with patch.object(t,'copy_source') as copy, patch.object(t,'scan') as scan:
            self.p._process_locked({'hash':self.key,'tags':''})
        copy.assert_not_called()
        scan.assert_not_called()
        self.p.qget.assert_not_called()
        self.p.tag.assert_called_once_with(self.key,'triagem-substituida')
        self.assertEqual(self.p.db.execute('SELECT status FROM items').fetchone()[0],'substituido')

    def test_existing_import_command_is_reused(self):
        self.p.arr.get.return_value.json.return_value = [{'id':17,'name':'DownloadedEpisodesScan','status':'started','body':{'path':'/data/aprovados/series/synthetic'}}]
        result = self.p.import_to_arr({'hash':self.key,'category':'sonarr'},t.PUBLIC/'series/synthetic')
        self.assertEqual(result,17)
        self.p.arr.post.assert_not_called()

    def test_import_failure_keeps_validated_copy(self):
        details={'name':'synthetic','destination':str(t.PUBLIC/'series/synthetic'),'files':{'video.mkv':'c'*64}}
        self.p.record(self.key,'pendente-importacao',details)
        self.p.import_to_arr = Mock(side_effect=TimeoutError('slow organizer'))
        with patch.object(t,'copy_source') as copy:
            with self.assertRaises(TimeoutError):
                self.p._process_locked({'hash':self.key,'category':'sonarr'})
        status,raw=self.p.db.execute('SELECT status,details FROM items').fetchone()
        self.assertEqual(status,'pendente-importacao')
        self.assertEqual(json.loads(raw)['files'],details['files'])
        self.assertEqual(json.loads(raw)['import_attempts'],1)
        copy.assert_not_called()

    def test_tag_failure_does_not_overwrite_approved_or_stop_other_items(self):
        details={'name':'synthetic','destination':'/approved/series/release','files':{'x.mkv':'c'*64},'import_command':17}
        self.p.record(self.key,'aprovado',details)
        torrent={'hash':self.key,'name':'synthetic','category':'sonarr','progress':1,'state':'stalledUP'}
        self.p.qget=Mock(return_value=[torrent])
        self.p.process=Mock(side_effect=RuntimeError('403 from qBittorrent'))
        self.p.tag=Mock(side_effect=RuntimeError('still unavailable'))
        with tempfile.TemporaryDirectory() as directory, patch.object(t,'PUBLIC',Path(directory)), patch.object(t.os,'chown'):
            (Path(directory)/'STATUS').mkdir()
            self.p.run()
        status,raw=self.p.db.execute('SELECT status,details FROM items').fetchone()
        self.assertEqual(status,'aprovado')
        self.assertEqual(json.loads(raw)['files'],details['files'])
        self.assertEqual(json.loads(raw)['import_command'],17)
        self.assertIn('403',json.loads(raw)['last_error'])

    def test_existing_destination_is_held_before_copy_or_scan(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(t,'PUBLIC',Path(directory)):
            root=Path(directory);destination=root/'series'/('synthetic__'+self.key[:8]);destination.mkdir(parents=True)
            (destination/'keep.mkv').write_bytes(b'existing')
            with patch.object(t,'copy_source') as copy, patch.object(t,'scan') as scan:
                self.p._process_locked({'hash':self.key,'name':'synthetic','category':'sonarr','tags':''})
            copy.assert_not_called();scan.assert_not_called()
            self.assertTrue((destination/'keep.mkv').exists())
            status,raw=self.p.db.execute('SELECT status,details FROM items').fetchone()
            self.assertEqual(status,'revisao');self.assertIn('histórico',json.loads(raw)['reason'])

    def test_new_import_has_suitable_response_timeout(self):
        self.p.arr.get.return_value.json.return_value=[]
        self.p.arr.post.return_value.json.return_value={'id':23}
        self.assertEqual(self.p.import_to_arr({'hash':self.key,'category':'sonarr'},t.PUBLIC/'series/synthetic'),23)
        self.assertEqual(self.p.arr.post.call_args.kwargs['timeout'],(10,90))

if __name__=='__main__':
    unittest.main()
