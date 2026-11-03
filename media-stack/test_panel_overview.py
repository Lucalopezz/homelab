#!/usr/bin/env python3
import datetime as dt
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('painel_local', Path(__file__).with_name('painel-local.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 3, 17, tzinfo=dt.timezone.utc)
        self.sync = {'data': {'pending': 13, 'at': '2026-11-03T16:59:00Z'}}

    def test_imported_but_not_published_is_not_complete(self):
        cleanup = {'active': True, 'data': {'state': 'aguardando_publicacao', 'at': '2026-11-03T16:59:30Z',
            'targets': {'Bleach': {'expected': 50, 'sonarr_missing': 0, 'jellyfin_missing': 17}}}}
        result = m.progress_overview(cleanup, self.sync, self.now)
        self.assertIn('pendente', result['title'].lower())
        self.assertTrue(any('33/50' in line for line in result['lines']))
        self.assertTrue(any('13 arquivo(s)' in line for line in result['lines']))

    def test_import_in_progress_does_not_claim_publication(self):
        cleanup = {'active': True, 'data': {'state': 'aguardando_importacao', 'at': '2026-11-03T16:59:30Z', 'progress': 'Processing file 11 of 26'}}
        result = m.progress_overview(cleanup, self.sync, self.now)
        self.assertIn('andamento', result['title'].lower())
        self.assertTrue(any('11 de 26' in line for line in result['lines']))

    def test_stale_or_inactive_waiter_is_not_reported_as_complete(self):
        old = {'active': True, 'data': {'state': 'aguardando_publicacao', 'at': '2026-11-03T16:00:00Z'}}
        self.assertIn('desatualizada', m.progress_overview(old, self.sync, self.now)['title'].lower())
        old['active'] = False
        self.assertIn('interrompido', m.progress_overview(old, self.sync, self.now)['title'].lower())


if __name__ == '__main__': unittest.main()
