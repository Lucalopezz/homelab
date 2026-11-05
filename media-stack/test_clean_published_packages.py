import importlib.util
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('packages',Path(__file__).with_name('clean-published-packages.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'jellyfin/state').mkdir(parents=True)
        self.record={'sha256':'a'*64,'stamp':[1,2,3,4]}
        self.published={'series/Show/Season 1/S01E01.mkv':self.record}
        self.torrent={'hash':'b'*40,'name':'Show','category':'sonarr','progress':1,'tags':'triagem-aprovada',
                      'state':'queuedUP','save_path':'/srv/downloads/recebidos/series','content_path':'/srv/downloads/recebidos/series/Show'}
        self.details={'name':'Show','files':{'Show/S01E01.mkv':'a'*64}}
        self.files=[{'name':'Show/S01E01.mkv','priority':1,'progress':1,'size':2}]
    def plan(self,torrents=None,details=None,present=None):
        (self.root/'jellyfin/state/published.json').write_text(json.dumps(self.published))
        torrents=torrents if torrents is not None else {self.torrent['hash']:self.torrent}
        details=details if details is not None else [(self.torrent['hash'],self.details)]
        catalog={'/lab-media/'+name for name in self.published}
        with patch.object(m,'ROOT',self.root),patch.object(m.m,'qlist',return_value=torrents),patch.object(m.m,'guest_rows',return_value=details),patch.object(m.m,'catalog',return_value=catalog),patch.object(m.m,'request',return_value=json.dumps(self.files).encode()),patch.object(m,'paths_exist',side_effect=lambda paths: present if present is not None else [True]*len(paths)):
            return m.build_plan(object())
    def test_approved_exact_published_file_is_candidate(self):
        plan=self.plan();self.assertEqual(len(plan),1);self.assertEqual(plan[0]['name'],'Show/S01E01.mkv')
    def test_rejected_if_not_approved(self):
        self.torrent['tags']='triagem-revisao';self.assertEqual(self.plan(),[])
    def test_rejected_if_unselected_or_incomplete(self):
        self.files[0]['priority']=0;self.assertEqual(self.plan(),[])
        self.files[0]['priority']=1;self.files[0]['progress']=.5;self.assertEqual(self.plan(),[])
    def test_rejected_if_jellyfin_digest_ambiguous(self):
        self.published['series/Another/duplicate.mkv']=self.record;self.assertEqual(self.plan(),[])
    def test_rejected_if_source_missing(self):
        self.assertEqual(self.plan(present=[False]),[])
    def test_rejected_if_another_torrent_shares_path(self):
        other={'hash':'c'*40,'content_path':'/srv/downloads/recebidos/series/Show'}
        self.assertEqual(self.plan(torrents={self.torrent['hash']:self.torrent,other['hash']:other}),[])
    def test_limit_counts_torrents_not_individual_files(self):
        files=[{'hash':'a','category':'sonarr','torrent':'Uma série','name':'S01E01'},
               {'hash':'b','category':'sonarr','torrent':'Outra série','name':'S01E01'},
               {'hash':'a','category':'sonarr','torrent':'Uma série','name':'S01E02'}]
        selected=m.select_plan(files,max_torrents=1)
        self.assertEqual([x['name'] for x in selected],['S01E01','S01E02'])
    def test_selection_can_filter_category_and_title(self):
        files=[{'hash':'a','category':'sonarr','torrent':'Uma Série'},
               {'hash':'b','category':'radarr','torrent':'Um Filme'}]
        self.assertEqual([x['hash'] for x in m.select_plan(files,'sonarr','série')],['a'])
        self.assertEqual([x['hash'] for x in m.select_plan(files,'radarr','filme')],['b'])
    def test_negative_torrent_limit_is_rejected(self):
        with self.assertRaises(ValueError):m.select_plan([],max_torrents=-1)
    def test_locked_cleanup_does_not_mark_existing_job_failed(self):
        journal=self.root/'status.json';lock=self.root/'cleanup.lock'
        original={'state':'limpando','files':[],'removed':3,'bytes':100}
        journal.write_text(json.dumps(original))
        with lock.open('a') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch.object(m,'LOCK',lock),patch.object(m,'JOURNAL',journal),patch.object(m,'RUN_STARTED',False):
                with self.assertRaises(BlockingIOError):m.main(True)
                self.assertFalse(m.RUN_STARTED)
        self.assertEqual(json.loads(journal.read_text()),original)
    def test_changed_filter_does_not_overwrite_interrupted_plan(self):
        journal=self.root/'status.json';lock=self.root/'cleanup.lock'
        original={'state':'erro','files':[],'removed':2,'bytes':100,'selection':{'category':'sonarr','title':'A','max_torrents':1}}
        journal.write_text(json.dumps(original))
        with patch.object(m,'LOCK',lock),patch.object(m,'JOURNAL',journal),patch.object(m,'RUN_STARTED',False),patch.object(m.m,'connect',return_value=object()):
            with self.assertRaisesRegex(RuntimeError,'filtros'):m.main(True,category='radarr')
            self.assertFalse(m.RUN_STARTED)
        self.assertEqual(json.loads(journal.read_text()),original)
    def test_other_save_root_is_rejected(self):
        self.torrent['save_path']='/srv/downloads/incompletos';self.assertEqual(self.plan(),[])

if __name__=='__main__':unittest.main()
