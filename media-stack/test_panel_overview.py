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

    def test_long_cleanup_uses_live_catalog_and_log_instead_of_old_start_time(self):
        cleanup = {'active': True, 'worker_active': True, 'data': {'state': 'limpando', 'at': '2026-11-03T16:00:00Z'},
                   'progress': {'removed': 3, 'bytes': 1073741824, 'current': 'series/exemplo.mkv', 'at': '03/11 às 13:59:30'}}
        jelly = {'at': '2026-11-03T17:00:00Z', 'targets': {
            'Family Guy': {'expected': 68, 'sonarr_missing': 0, 'jellyfin_missing': 0},
            'Bleach': {'expected': 50, 'sonarr_missing': 0, 'jellyfin_missing': 0},
            'Star Wars: The Clone Wars': {'expected': 133, 'sonarr_missing': 0, 'jellyfin_missing': 0}}}
        result = m.progress_overview(cleanup, self.sync, self.now, jellyfin=jelly)
        self.assertEqual(result['title'], 'Limpeza em andamento')
        self.assertEqual(result['at'], jelly['at'])
        self.assertTrue(any('3 vídeo(s)' in line and '1.0 GiB' in line for line in result['lines']))
        self.assertTrue(any('50/50' in line for line in result['lines']))
        cleanup['worker_active'] = False
        self.assertIn('não confirmado', m.progress_overview(cleanup, self.sync, self.now, jellyfin=jelly)['title'].lower())

    def test_log_reports_only_latest_cleanup_batch(self):
        log = '\n'.join(['{"candidatos": 10, "modo": "aplicar"}',
                         '{"removido": "velho.mkv", "bytes": 10}',
                         '{"candidatos": 4, "modo": "aplicar"}',
                         'Conferindo: primeiro.mkv', '{"removido": "primeiro.mkv", "bytes": 100}',
                         'Conferindo: segundo.mkv'])
        self.assertEqual(m.parse_cleanup_log(log), {'candidates': 4, 'removed': 1, 'bytes': 100, 'current': 'segundo.mkv'})

    def test_unavailable_catalog_is_not_reported_as_current(self):
        cleanup = {'active': True, 'worker_active': True, 'data': {'state': 'limpando', 'at': '2026-11-03T16:00:00Z',
            'targets': {'Bleach': {'expected': 50, 'sonarr_missing': 0, 'jellyfin_missing': 0}}}}
        result = m.progress_overview(cleanup, self.sync, self.now, jellyfin={'error': 'Timeout'})
        self.assertTrue(any('Catálogo atual indisponível' in line for line in result['lines']))
        self.assertEqual(result['at'], cleanup['data']['at'])


if __name__ == '__main__': unittest.main()
