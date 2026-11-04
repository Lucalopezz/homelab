#!/usr/bin/env python3
import datetime as dt
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('painel_local', Path(__file__).with_name('painel-local.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,4,tzinfo=dt.timezone.utc)
        self.series=[{'id':1,'title':'Série antiga','tvdbId':101,'monitored':True,'path':'/data/biblioteca/series/Antiga'},
                     {'id':2,'title':'Série nova','tvdbId':202,'monitored':True,'path':'/data/biblioteca/series/Nova'}]
        self.episodes={1:[self.ep(1,True)],2:[self.ep(1,False),self.ep(2,False)]}
        self.jseries=[{'Id':'j1','Path':'/lab-media/series/Antiga','ProviderIds':{'Tvdb':'101'}}]
        self.jeps=[{'SeriesId':'j1','Path':'/lab-media/series/Antiga/S01E01.mkv','ParentIndexNumber':1,'IndexNumber':1}]
    def ep(self,n,has_file,**kw):
        return dict({'seasonNumber':1,'episodeNumber':n,'monitored':True,'hasFile':has_file,'airDateUtc':'2020-01-01T00:00:00Z'},**kw)
    def status(self):return m.catalog_status(self.series,self.episodes,self.jseries,self.jeps,self.now)
    def test_new_series_appears_even_when_old_cleanup_finished(self):
        targets=self.status(); self.assertEqual(targets['Série antiga']['jellyfin_missing'],0)
        self.assertEqual(targets['Série nova'],{'expected':2,'sonarr_missing':2,'jellyfin_missing':2})
        summary=m.progress_overview({'data':{'state':'concluido'}},{'data':{'pending':0}},jellyfin={'targets':targets})
        self.assertTrue(any('Série nova: 0/2' in line for line in summary['lines']))
        self.assertNotIn('concluíd',summary['title'].lower())
    def test_only_monitored_released_episodes_are_counted(self):
        self.episodes[2]+=[self.ep(3,False,airDateUtc='2030-01-01T00:00:00Z'),self.ep(4,False,monitored=False),self.ep(5,False,seasonNumber=0)]
        self.assertEqual(self.status()['Série nova']['expected'],2)
    def test_partial_jellyfin_publication_uses_series_id_not_title(self):
        self.jseries.append({'Id':'j2','Path':'/lab-media/series/Nova','ProviderIds':{'Tvdb':'202'}})
        self.jeps.append({'SeriesId':'j2','Path':'/lab-media/series/Nova/file.mkv','ParentIndexNumber':1,'IndexNumber':2})
        self.assertEqual(self.status()['Série nova']['jellyfin_missing'],1)
    def test_missing_episode_response_is_unknown_not_zero(self):
        self.episodes[2]=None
        self.assertIn('error',self.status()['Série nova'])
    def test_ambiguous_jellyfin_match_is_not_counted(self):
        self.jseries.append({'Id':'other','Path':'/lab-media/series/Other','ProviderIds':{'Tvdb':'101'}})
        self.assertIn('error',self.status()['Série antiga'])
    def test_unavailable_jellyfin_does_not_reuse_old_cleanup(self):
        result=m.progress_overview({'data':{'state':'concluido','targets':{'Antiga':{'expected':1}}}}, {}, jellyfin={'error':'Timeout'})
        self.assertTrue(any('não está confirmado' in line for line in result['lines']))
        self.assertFalse(any('Antiga' in line for line in result['lines']))
    def test_new_movie_is_reported_and_catalog_matched_by_tmdb(self):
        movies=[{'title':'Filme antigo','tmdbId':1,'monitored':True,'hasFile':True},
                {'title':'Filme novo','tmdbId':2,'monitored':True,'hasFile':False}]
        jelly=[{'Path':'/lab-media/filmes/antigo/movie.mkv','ProviderIds':{'Tmdb':'1'}}]
        result=m.movie_catalog_status(movies,jelly)
        self.assertTrue(result['Filme antigo']['jellyfin'])
        self.assertFalse(result['Filme novo']['jellyfin'])
        summary=m.progress_overview({}, {}, jellyfin={'targets':{},'movies':result})
        self.assertTrue(any('Filme novo' in line and 'ainda não' in line for line in summary['lines']))

    def test_log_reports_only_latest_cleanup_batch(self):
        log='\\n'.join(['{"candidatos": 10, "modo": "aplicar"}','{"removido": "velho.mkv", "bytes": 10}', '{"candidatos": 4, "modo": "aplicar"}', 'Conferindo: primeiro.mkv', '{"removido": "primeiro.mkv", "bytes": 100}', 'Conferindo: segundo.mkv']).replace('\\n','\n')
        self.assertEqual(m.parse_cleanup_log(log),{'candidates':4,'removed':1,'bytes':100,'current':'segundo.mkv'})

if __name__=='__main__':unittest.main()
