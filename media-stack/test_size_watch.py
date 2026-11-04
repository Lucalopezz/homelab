import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('size_watch', Path(__file__).with_name('size-watch.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class Response:
    def __init__(self, value=None): self.value = value
    def raise_for_status(self): pass
    def json(self): return self.value

class Session:
    def __init__(self, files, releases=None, parsed=None):
        self.files = files; self.releases = releases or []; self.parsed = parsed; self.posts = []
    def get(self, url, **kwargs):
        if url.endswith('torrents/files'): return Response(self.files)
        if url.endswith('/parse'): return Response(self.parsed)
        if url.endswith('/release'): return Response(self.releases)
        raise AssertionError(url)
    def post(self, url, **kwargs): self.posts.append((url, kwargs)); return Response()

class SizeWatchTest(unittest.TestCase):
    def item(self, name, size, priority=1): return {'name':name, 'size':size, 'priority':priority}
    def check(self, session, state=None, torrent=None):
        state = state if state is not None else {}
        torrent = torrent or {'hash':'abc', 'name':'Series S01', 'category':'sonarr', 'state':'downloading'}
        m.inspect(session, 'http://qb/api/v2/', {'url':'http://sonarr', 'api_key':'fake'}, [torrent], state, lambda:None, now=100000)
        return state
    def test_extra_deselected_but_episode_kept(self):
        s=Session([self.item('Series/Extras/bonus.mkv',m.LIMIT+1),self.item('Series/S01E01.mkv',500)])
        state=self.check(s)
        self.assertEqual(state['items']['abc:0']['status'],'extra-ignorado')
        self.assertEqual(len(s.posts),1); self.assertEqual(s.posts[0][1]['data']['priority'],0)
    def test_extra_only_video_not_deselected(self):
        s=Session([self.item('Series/Extras/bonus.mkv',m.LIMIT+1)])
        state=self.check(s); self.assertFalse(s.posts); self.assertEqual(state['items']['abc:0']['status'],'revisao')
    def test_selects_only_approved_small_single_episode_and_skips_original(self):
        parsed={'series':{'id':2},'episodes':[{'id':7,'seasonNumber':1,'episodeNumber':1}]}
        releases=[{'title':'Series.S01E01','approved':True,'size':m.LIMIT+1,'protocol':'torrent','seeders':20,'guid':'large','indexerId':1},
                  {'title':'Series.S01E01','approved':True,'size':500,'protocol':'torrent','seeders':2,'guid':'small','indexerId':1}]
        s=Session([self.item('Series/Series.S01E01.mkv',m.LIMIT+1),self.item('Series/Series.S01E02.mkv',500)],releases,parsed)
        state=self.check(s); self.assertEqual(s.posts[0][1]['json']['guid'],'small');self.assertEqual(s.posts[1][1]['data']['priority'],0)
        self.assertEqual(state['items']['abc:0']['status'],'alternativa-solicitada')
    def test_no_eligible_release_does_not_deselect_original(self):
        parsed={'series':{'id':2},'episodes':[{'id':7,'seasonNumber':1,'episodeNumber':1}]}
        s=Session([self.item('Series/Series.S01E01.mkv',m.LIMIT+1),self.item('Series/Series.S01E02.mkv',500)],[],parsed)
        state=self.check(s);self.assertFalse(s.posts);self.assertEqual(state['items']['abc:0']['status'],'sem-fonte')
    def test_completed_torrent_never_changed(self):
        s=Session([self.item('Series/Extras/bonus.mkv',m.LIMIT+1),self.item('Series/S01E01.mkv',500)])
        state=self.check(s,torrent={'hash':'abc','category':'sonarr','state':'uploading'})
        self.assertFalse(s.posts);self.assertFalse(state['items'])
    def test_ambiguous_episode_unchanged(self):
        s=Session([self.item('Series/Series.S01E01E02.mkv',m.LIMIT+1),self.item('Series/Series.S01E03.mkv',500)])
        state=self.check(s);self.assertFalse(s.posts);self.assertEqual(state['items']['abc:0']['status'],'revisao')

if __name__ == '__main__': unittest.main()
