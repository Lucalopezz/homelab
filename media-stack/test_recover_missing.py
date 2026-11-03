#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('recover_missing', Path(__file__).with_name('recover-missing.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class RecoveryTests(unittest.TestCase):
    def test_search_is_blocked_for_existing_or_ambiguous_sources(self):
        self.assertFalse(m.should_search(1, 2, {1}, set(), False, {}, 100000))
        self.assertFalse(m.should_search(1, 2, set(), {2}, False, {}, 100000))
        self.assertFalse(m.should_search(1, 2, set(), set(), True, {}, 100000))
        self.assertTrue(m.should_search(1, 2, set(), set(), False, {}, 100000))

    def test_search_backoff_and_maximum(self):
        self.assertFalse(m.should_search(1, 2, set(), set(), False, {'1': {'count': 1, 'at': 90000}}, 100000))
        self.assertFalse(m.should_search(1, 2, set(), set(), False, {'1': {'count': 3, 'at': 0}}, 100000))
        self.assertTrue(m.should_search(1, 2, set(), set(), False, {'1': {'count': 2, 'at': 0}}, 100000))

    def test_packs_and_anime_use_resolved_episode_ids(self):
        self.assertEqual(m.classify_parse({'series': {'id': 3}, 'episodes': [{'id': 10}, {'id': 11}]}), (3, {10, 11}))
        self.assertEqual(m.classify_parse({'series': {'id': 2}, 'episodes': [{'id': 1054}]}), (2, {1054}))
        self.assertEqual(m.classify_parse({'series': {'id': 2}, 'episodes': []}), (2, set()))
        self.assertEqual(m.classify_parse({}), (None, set()))

    def test_anime_number_requires_explicit_matching_evidence(self):
        episode = {'season': 17, 'episode': 5, 'absolute': 371}
        self.assertTrue(m.explicit_episode_match('Bleach S17E05 WEB', episode))
        self.assertTrue(m.explicit_episode_match('Bleach S01E05 [EP: 371]', episode))
        self.assertFalse(m.explicit_episode_match('Bleach S01E05 [EP: 370]', episode))
        self.assertFalse(m.explicit_episode_match('Bleach S17E50', episode))

    def test_rejects_traversal_and_hidden_paths(self):
        self.assertTrue(m.safe_relative('Temporada/Episodio.mkv'))
        for path in ('../x.mkv', '/tmp/x.mkv', 'temporada/../x.mkv', '.oculto/x.mkv', 'x\\y.mkv'):
            self.assertFalse(m.safe_relative(path), path)

    def make_recovery(self, parsed):
        rec = object.__new__(m.Recovery)
        rec.active_commands = lambda: []
        def get(path, **kw):
            if path == 'series': return [{'id': 2, 'monitored': True}]
            if path == 'episode': return [{'id': 1054, 'seasonNumber': 17, 'episodeNumber': 5, 'monitored': True, 'hasFile': False, 'airDateUtc': '2022-10-25T14:00:00Z'}]
            raise AssertionError(path)
        rec.get = get
        rec.torrents = lambda: [{'category': 'sonarr', 'state': 'queuedUP', 'tags': 'triagem-aprovada', 'name': 'arquivo existente'}]
        rec.parse = lambda title: parsed
        rec.approved_rows = lambda: []
        rec.post = lambda *a, **kw: self.fail('não deveria acionar uma busca')
        return rec

    def test_complete_download_prevents_duplicate_search(self):
        with tempfile.TemporaryDirectory() as d, patch.object(m, 'STATE', Path(d)):
            result = self.make_recovery((2, {1054})).run(apply=True)
        self.assertEqual(result['action'], 'none')
        self.assertEqual(result['eligible_searches'], [])

    def test_unknown_download_prevents_guessing(self):
        with tempfile.TemporaryDirectory() as d, patch.object(m, 'STATE', Path(d)):
            result = self.make_recovery((None, set())).run(apply=True)
        self.assertTrue(result['unknown_source'])
        self.assertEqual(result['eligible_searches'], [])

    def test_existing_import_blocks_another_action(self):
        rec = object.__new__(m.Recovery)
        rec.active_commands = lambda: [{'name': 'ManualImport', 'status': 'started'}]
        rec.get = lambda *a, **kw: self.fail('não consultar enquanto a importação está ativa')
        self.assertEqual(rec.run(apply=True)['action'], 'none')

    def test_approved_file_is_imported_once_and_not_searched(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); approved = root / 'approved'; source = approved / 'release'; source.mkdir(parents=True)
            video = source / 'episode.mkv'; video.write_bytes(b'video sintetico')
            h = 'a' * 40; digest = 'b' * 64
            marker = source / 'TRIAGEM.json'
            marker.write_text(json.dumps({'hash': h, 'scanner': 'ClamAV', 'sha256': {'episode.mkv': digest}}))
            marker.chmod(0o440)
            rec = self.make_recovery((2, {1054}))
            rec.torrents = lambda: []
            rec.approved_rows = lambda: [(h, {'name': 'Anime S17E05', 'destination': str(source), 'files': {'episode.mkv': digest}})]
            original_get = rec.get
            def get(path, **kw):
                if path == 'manualimport':
                    return [{'path': kw['folder'], 'series': {'id': 2}, 'episodes': [{'id': 1054}],
                             'rejections': [], 'quality': {}, 'languages': []}]
                return original_get(path, **kw)
            rec.get = get
            calls = []
            rec.post = lambda name, **kw: calls.append((name, kw)) or {'id': 7}
            with patch.object(m, 'STATE', root), patch.object(m, 'APPROVED', approved):
                first = rec.run(apply=True)
                second = rec.run(apply=True)
            self.assertEqual(first['action'], 'import')
            self.assertEqual(first['episode_ids'], [1054])
            self.assertEqual(second['action'], 'none')
            self.assertEqual([x[0] for x in calls], ['ManualImport'])

    def test_search_attempt_is_persisted_before_post(self):
        with tempfile.TemporaryDirectory() as d, patch.object(m, 'STATE', Path(d)):
            rec = self.make_recovery((None, set()))
            rec.torrents = lambda: []
            def post(name, **kwargs):
                saved = json.loads((Path(d) / 'attempts.json').read_text())
                self.assertEqual(saved['1054']['status'], 'enviando')
                return {'id': 8}
            rec.post = post
            first = rec.run(apply=True)
            second = rec.run(apply=True)
            self.assertEqual(first['action'], 'search')
            self.assertEqual(second['action'], 'none')


if __name__ == '__main__': unittest.main()
