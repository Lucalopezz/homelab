#!/usr/bin/env python3
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('clean_after_import', Path(__file__).with_name('clean-after-import.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class WaitCleanupTests(unittest.TestCase):
    def episode(self, num=1, has_file=True):
        return {'seasonNumber': 1, 'episodeNumber': num, 'airDateUtc': '2022-01-01T00:00:00Z', 'hasFile': has_file}

    def item(self, num=1):
        return {'Path': '/lab-media/series/Example/Season 1/example.mkv', 'ParentIndexNumber': 1, 'IndexNumber': num}

    def test_requires_both_import_and_catalog(self):
        now = dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc)
        result = m.target_status([self.episode(1), self.episode(2, False)], [self.item(1)], 'Example', {1}, 2, now)
        self.assertEqual(result, {'expected': 2, 'sonarr_missing': 1, 'jellyfin_missing': 1})
        with self.assertRaises(ValueError):
            m.target_status([self.episode()], [self.item()], 'Example', {1}, 2, now)

    def run_scenario(self, command, items, episodes):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); state = root / 'state'; state.mkdir(); (root / 'secrets').mkdir(); (root / 'jellyfin/state').mkdir(parents=True)
            (root / 'secrets/media-stack.json').write_text(json.dumps({'sonarr_key': 'synthetic'}))
            (root / 'secrets/jellyfin-host.json').write_text(json.dumps({'api_key': 'synthetic'}))
            (root / 'jellyfin/state/last-run.json').write_text(json.dumps({'pending': 0, 'held': []}))
            class FakeResponse:
                def __init__(self, data): self.data = data
                def raise_for_status(self): pass
                def json(self): return self.data
            class FakeSession:
                trust_env = True
                def get(self, url, **kwargs):
                    if url.endswith('/command/5238'): return FakeResponse({'status': command})
                    if url.endswith('/Items'): return FakeResponse({'Items': items, 'TotalRecordCount': len(items)})
                    if url.endswith('/episode'): return FakeResponse(episodes)
                    if url.endswith('/command'): return FakeResponse([])
                    raise AssertionError(url)
            calls = []
            def run(cmd, **kwargs):
                calls.append(cmd)
                return SimpleNamespace(stdout='inactive\n', returncode=0)
            targets = {'Example': {'series_id': 1, 'seasons': {1}, 'minimum': 1, 'folder': 'Example'}}
            with patch.object(m, 'ROOT', root), patch.object(m, 'STATE', state), patch.object(m, 'TARGETS', targets), patch.object(m.requests, 'Session', FakeSession), patch.object(m.subprocess, 'run', side_effect=run), patch.object(m.time, 'sleep', side_effect=StopIteration):
                try: m.main()
                except StopIteration: pass
            status = json.loads((state / 'cleanup-after-import-status.json').read_text())
            return status, calls

    def test_does_not_clean_during_import(self):
        status, calls = self.run_scenario('started', [], [self.episode()])
        self.assertEqual(status['state'], 'aguardando_importacao')
        self.assertEqual(calls, [])

    def test_does_not_clean_when_episode_is_not_in_jellyfin(self):
        status, calls = self.run_scenario('completed', [], [self.episode()])
        self.assertEqual(status['state'], 'aguardando_publicacao')
        self.assertFalse(any(cmd[0] == 'ionice' for cmd in calls))

    def test_starts_cleanup_only_when_import_and_catalog_are_complete(self):
        status, calls = self.run_scenario('completed', [self.item()], [self.episode()])
        self.assertEqual(status['state'], 'concluido')
        self.assertTrue(any(cmd[0] == 'ionice' for cmd in calls))


if __name__ == '__main__': unittest.main()
