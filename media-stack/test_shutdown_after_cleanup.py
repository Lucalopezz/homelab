import importlib.util
from pathlib import Path
import unittest
import json
import tempfile
import datetime as dt
from unittest.mock import patch,Mock

spec=importlib.util.spec_from_file_location('shutdown',Path(__file__).with_name('shutdown-after-cleanup.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ShutdownDecisionTests(unittest.TestCase):
    def test_only_completed_cleanup_is_ready(self):
        self.assertEqual(m.cleanup_decision('concluido',False),'ready')
        self.assertEqual(m.cleanup_decision('limpando',True),'wait')
        self.assertEqual(m.cleanup_decision('erro',False),'error')
        self.assertEqual(m.cleanup_decision('limpando',False),'interrupted')
        self.assertEqual(m.cleanup_decision(None,False),'interrupted')
    def test_pending_download_states_are_detectable(self):
        self.assertIn('downloading',m.ACTIVE_DOWNLOADS)
        self.assertIn('queuedDL',m.ACTIVE_DOWNLOADS)
        self.assertIn('moving',m.ACTIVE_PROCESSING)
        self.assertIn('checkingUP',m.ACTIVE_PROCESSING)
        self.assertNotIn('stalledUP',m.ACTIVE_DOWNLOADS)

class ConfigurationTests(unittest.TestCase):
    def test_cleanup_file_must_be_inside_state_and_process_is_a_basename(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(m,'ROOT',Path(directory)):
            state=Path(directory)/'state';state.mkdir()
            target,process=m.configured_cleanup(state/'example.json','cleanup.py')
            self.assertEqual(target,state/'example.json');self.assertEqual(process,'cleanup.py')
            with self.assertRaises(ValueError):m.configured_cleanup(Path(directory)/'outside.json','cleanup.py')
            with self.assertRaises(ValueError):m.configured_cleanup(state/'example.json','../cleanup.py')

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'secrets').mkdir();(self.root/'jellyfin/state').mkdir(parents=True)
        (self.root/'secrets/media-stack.json').write_text(json.dumps({'sonarr_key':'fake','radarr_key':'fake'}))
        (self.root/'jellyfin/state/last-run.json').write_text(json.dumps({'at':dt.datetime.now(dt.timezone.utc).isoformat(),'pending':0,'held':[]}))
        self.cleanup=self.root/'cleanup.json';self.cleanup.write_text(json.dumps({'state':'concluido'}))
    def check(self,torrents=None,commands=None,triage='inactive',sync='inactive'):
        response=Mock();response.json.return_value=commands or []
        session=Mock();session.get.return_value=response
        def run(cmd,**kwargs):
            result=Mock();result.stdout=(triage if cmd and cmd[0]=='ssh' else sync)+'\n';return result
        with patch.object(m,'ROOT',self.root),patch.object(m,'CLEANUP',self.cleanup),patch.object(m,'SSH',['ssh']),patch.object(m,'connect',return_value=object()),patch.object(m,'request',return_value=json.dumps(torrents or []).encode()),patch.object(m.requests,'Session',return_value=session),patch.object(m.subprocess,'run',side_effect=run):
            return m.safe_to_shutdown()
    def test_idle_services_allow_shutdown(self):
        self.assertEqual(self.check(),(True,None))
    def test_running_download_blocks_shutdown(self):
        self.assertFalse(self.check(torrents=[{'progress':.5,'state':'downloading'}])[0])
    def test_verifying_completed_torrent_blocks_shutdown(self):
        self.assertFalse(self.check(torrents=[{'progress':1,'state':'checkingUP'}])[0])
    def test_queued_import_blocks_shutdown(self):
        self.assertFalse(self.check(commands=[{'name':'ManualImport','status':'queued'}])[0])
    def test_active_triage_or_sync_blocks_shutdown(self):
        self.assertFalse(self.check(triage='activating')[0])
        self.assertFalse(self.check(sync='active')[0])
        self.assertFalse(self.check(sync='failed')[0])
    def test_pending_sync_blocks_shutdown(self):
        (self.root/'jellyfin/state/last-run.json').write_text(json.dumps({'at':dt.datetime.now(dt.timezone.utc).isoformat(),'pending':1,'held':[]}))
        self.assertFalse(self.check()[0])

if __name__=='__main__':unittest.main()
