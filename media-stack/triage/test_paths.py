"""Testes de barreiras de arquivo: links, travessia, FIFO e limites de análise."""
import importlib.util
from pathlib import Path
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

spec = importlib.util.spec_from_file_location('triage', Path(__file__).with_name('triage.py'))
triage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage)

class FileBarrierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir='/mnt/dados/lab/state')
        self.root = Path(self.temporary.name)
        self.raw = self.root/'raw'
        self.raw.mkdir()
        triage.RAW = self.raw
        self.outside = self.root/'outside'
        self.outside.mkdir()
        (self.outside/'private.txt').write_text('não deve ser copiado')

    def tearDown(self):
        self.temporary.cleanup()

    def test_file_symlink_is_rejected(self):
        (self.raw/'video.mkv').symlink_to(self.outside/'private.txt')
        with self.assertRaises(OSError):
            triage.open_source(self.raw/'video.mkv')

    def test_directory_symlink_is_rejected(self):
        (self.raw/'show').symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(OSError):
            triage.open_source(self.raw/'show/private.txt')

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(triage.Rejected):
            triage.open_source(self.raw/'../outside/private.txt')

    def test_fifo_does_not_block_or_get_copied(self):
        os.mkfifo(self.raw/'video.mkv')
        with self.assertRaises(triage.Rejected):
            triage.open_source(self.raw/'video.mkv')

    def test_file_above_scan_limit_is_not_released(self):
        source = self.raw/'large.mkv'
        with source.open('wb') as handle:
            handle.truncate(triage.MAX_BYTES+1)
        with self.assertRaises(triage.Review):
            triage.copy_source(source, self.root/'copy.mkv')
        self.assertFalse((self.root/'copy.mkv').exists())

    def test_copy_has_its_own_inode(self):
        source = self.raw/'video.mkv'
        source.write_bytes(b'conteudo de teste')
        destination = self.root/'copy.mkv'
        triage.copy_source(source, destination)
        source.write_bytes(b'origem alterada depois da copia')
        self.assertEqual(destination.read_bytes(), b'conteudo de teste')
        self.assertNotEqual(source.stat().st_ino, destination.stat().st_ino)

class SelectedMediaTests(unittest.TestCase):
    def item(self, name, priority=1, progress=1, size=100):
        return dict(name=name, priority=priority, progress=progress, size=size)

    def test_only_selected_complete_episode_enters_approval_manifest(self):
        accepted = triage.selected_media([self.item('S05E10.mkv', 0, 0),
                                          self.item('S05E11.mkv'),
                                          self.item('S05E12.mkv', 0, 0)])
        self.assertEqual([x[0]['name'] for x in accepted], ['S05E11.mkv'])

    def test_incomplete_selected_video_is_still_refused(self):
        with self.assertRaises(triage.Review):
            triage.selected_media([self.item('S05E11.mkv', progress=0.9)])

    def test_unselected_executable_still_refuses_distribution(self):
        with self.assertRaises(triage.Rejected):
            triage.selected_media([self.item('S05E11.mkv'), self.item('bad.exe', 0, 0)])

    def test_no_selected_video_is_not_approved(self):
        with self.assertRaises(triage.Rejected):
            triage.selected_media([self.item('S05E11.mkv', 0, 0)])

    def test_unselected_parent_traversal_is_still_refused(self):
        with self.assertRaises(triage.Rejected):
            triage.selected_media([self.item('S05E11.mkv'), self.item('../other.mkv', 0, 0)])

class StatusTests(unittest.TestCase):
    def test_reviewed_item_restores_label_without_scanning_again(self):
        pipeline = triage.Pipeline.__new__(triage.Pipeline)
        pipeline.db = sqlite3.connect(':memory:')
        self.addCleanup(pipeline.db.close)
        pipeline.db.execute('CREATE TABLE items (hash TEXT PRIMARY KEY, status TEXT, details TEXT, updated TEXT)')
        key = 'a' * 40
        pipeline.db.execute('INSERT INTO items VALUES (?,?,?,?)', (key, 'revisao', '{}', 'now'))
        pipeline.tag = Mock()
        pipeline._process_locked({'hash': key, 'tags': 'triagem-pendente'})
        pipeline.tag.assert_called_once_with(key, 'triagem-revisao')
        self.assertEqual(pipeline.db.execute('SELECT status FROM items').fetchone()[0], 'revisao')
        pipeline.tag.reset_mock()
        pipeline._process_locked({'hash': key, 'tags': 'triagem-revisao'})
        pipeline.tag.assert_not_called()


class ScannerQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir='/mnt/dados/lab/state')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'clamav-scan.lock').touch()
        self.state_patch = patch.object(triage, 'STATE', self.root)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def test_parallel_clients_wait_outside_scanner_timeout(self):
        guard = threading.Lock()
        running, peak = 0, 0

        def scanner(*args, **kwargs):
            nonlocal running, peak
            self.assertGreater(kwargs['timeout'], 1200)
            with guard:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with guard:
                running -= 1
            return subprocess.CompletedProcess([], 0, '', '')

        with patch.object(triage.subprocess, 'run', side_effect=scanner):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(triage.scan, [self.root / 'a.mp4', self.root / 'b.mp4']))
        self.assertEqual(peak, 1)

    def test_timeout_still_refuses_approval(self):
        with patch.object(triage.subprocess, 'run', side_effect=subprocess.TimeoutExpired('clamdscan', 1260)):
            with self.assertRaisesRegex(RuntimeError, 'arquivo não liberado'):
                triage.scan(self.root / 'video.mp4')


class RecoveryStateTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = triage.Pipeline.__new__(triage.Pipeline)
        self.pipeline.db = sqlite3.connect(':memory:')
        self.addCleanup(self.pipeline.db.close)
        self.pipeline.db.execute('CREATE TABLE items (hash TEXT PRIMARY KEY,status TEXT,details TEXT,updated TEXT)')
        self.pipeline.db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY,hash TEXT,previous_status TEXT,status TEXT,previous_details TEXT,details TEXT,at TEXT)')
        self.pipeline.config = {'sonarr': {'url': 'http://organizer', 'api_key': 'synthetic'}}
        self.pipeline.arr = Mock()
        self.pipeline.tag = Mock()
        self.key = 'b' * 40

    def test_recovery_preserves_old_failure_in_history(self):
        self.pipeline.record(self.key, 'erro', {'reason': 'old timeout'})
        self.pipeline.record(self.key, 'reanalise-agendada', {'name': 'synthetic'})
        old, new, details = self.pipeline.db.execute('SELECT previous_status,status,previous_details FROM events ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual((old, new), ('erro', 'reanalise-agendada'))
        self.assertEqual(__import__('json').loads(details)['reason'], 'old timeout')

    def test_superseded_download_is_never_scanned_or_approved(self):
        self.pipeline.record(self.key, 'substituido', {'replacement_hashes': ['c' * 40]})
        self.pipeline.qget = Mock()
        with patch.object(triage, 'copy_source') as copy, patch.object(triage, 'scan') as scan:
            self.pipeline._process_locked({'hash': self.key, 'tags': ''})
        copy.assert_not_called()
        scan.assert_not_called()
        self.pipeline.qget.assert_not_called()
        self.pipeline.tag.assert_called_once_with(self.key, 'triagem-substituida')
        self.assertEqual(self.pipeline.db.execute('SELECT status FROM items').fetchone()[0], 'substituido')

    def test_import_reuses_active_command_for_same_path(self):
        torrent = {'hash': self.key, 'category': 'sonarr'}
        self.pipeline.arr.get.return_value.json.return_value = [{'id': 17, 'name': 'DownloadedEpisodesScan', 'status': 'started', 'body': {'path': '/data/aprovados/series/synthetic'}}]
        result = self.pipeline.import_to_arr(torrent, triage.PUBLIC / 'series/synthetic')
        self.assertEqual(result, 17)
        self.pipeline.arr.post.assert_not_called()

    def test_import_failure_keeps_approved_files_and_records_attempt(self):
        import json
        details = {'name': 'synthetic', 'destination': str(triage.PUBLIC / 'series/synthetic'), 'files': {'video.mkv': 'c' * 64}}
        self.pipeline.record(self.key, 'pendente-importacao', details)
        self.pipeline.import_to_arr = Mock(side_effect=TimeoutError('slow organizer'))
        with patch.object(triage, 'copy_source') as copy:
            with self.assertRaises(TimeoutError):
                self.pipeline._process_locked({'hash': self.key, 'category': 'sonarr'})
        status, raw = self.pipeline.db.execute('SELECT status,details FROM items').fetchone()
        self.assertEqual(status, 'pendente-importacao')
        self.assertEqual(json.loads(raw)['files'], details['files'])
        self.assertEqual(json.loads(raw)['import_attempts'], 1)
        copy.assert_not_called()

    def test_new_import_uses_longer_timeout_and_returns_command(self):
        self.pipeline.arr.get.return_value.json.return_value = []
        self.pipeline.arr.post.return_value.json.return_value = {'id': 23}
        result = self.pipeline.import_to_arr({'hash': self.key, 'category': 'sonarr'}, triage.PUBLIC / 'series/synthetic')
        self.assertEqual(result, 23)
        self.assertEqual(self.pipeline.arr.post.call_args.kwargs['timeout'], (10, 90))


if __name__ == '__main__':
    unittest.main()
