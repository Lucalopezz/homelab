import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

spec=importlib.util.spec_from_file_location('series_status',Path(__file__).with_name('series-status.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SeriesStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'secrets').mkdir();(self.root/'secrets/media-stack.json').write_text(json.dumps({'sonarr_key':'fake'}))
        self.series=[{'id':9,'title':'Exemplo','monitored':True}]
    def args(self,**changes):
        data={'list':False,'id':9,'title':None,'seasons':None,'rescan':False,'wait':False,'timeout':10};data.update(changes);return argparse.Namespace(**data)
    def test_title_selection_requires_unambiguous_exact_match(self):
        self.assertEqual(m.choose_series(self.series,title='exemplo')['id'],9)
        with self.assertRaises(ValueError):m.choose_series(self.series+self.series,title='Exemplo')
        with self.assertRaises(ValueError):m.choose_series(self.series,title='outra')
    def test_seasons_and_busy_commands(self):
        self.assertEqual(m.parse_seasons('1, 3'),{1,3})
        with self.assertRaises(argparse.ArgumentTypeError):m.parse_seasons('0,2')
        self.assertEqual(len(m.busy_commands([{'name':'ManualImport','status':'queued'},{'name':'RescanSeries','status':'completed'}])),1)
    def test_read_only_does_not_request_rescan(self):
        response=Mock();response.json.return_value=self.series
        session=Mock();session.get.return_value=response
        with patch.object(m,'ROOT',self.root),patch.object(m.requests,'Session',return_value=session),patch.object(m,'report',return_value={'episodios_lancados':2}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(self.args()),0)
        session.post.assert_not_called()
    def test_rescan_does_not_start_during_import(self):
        series_response=Mock();series_response.json.return_value=self.series
        commands_response=Mock();commands_response.json.return_value=[{'name':'DownloadedEpisodesScan','status':'started'}]
        session=Mock();session.get.side_effect=[series_response,commands_response]
        with patch.object(m,'ROOT',self.root),patch.object(m.requests,'Session',return_value=session):
            with self.assertRaisesRegex(RuntimeError,'andamento'):m.main(self.args(rescan=True))
        session.post.assert_not_called()
    def test_rescan_submitted_when_idle(self):
        series_response=Mock();series_response.json.return_value=self.series
        commands_response=Mock();commands_response.json.return_value=[]
        submitted=Mock();submitted.json.return_value={'id':32,'status':'queued'}
        session=Mock();session.get.side_effect=[series_response,commands_response];session.post.return_value=submitted
        with patch.object(m,'ROOT',self.root),patch.object(m.requests,'Session',return_value=session),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(self.args(rescan=True)),0)
        self.assertEqual(session.post.call_args.kwargs['json'],{'name':'RescanSeries','seriesId':9})

if __name__=='__main__':unittest.main()
