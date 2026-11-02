"""Casos de progresso, fila, reinício e retomada sem usar downloads reais."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('watch', Path(__file__).with_name('download-watch.py'))
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class WatchTests(unittest.TestCase):
    def torrent(self, **changes):
        item = dict(hash='a' * 40, category='sonarr', state='stalledDL',
                    progress=0.2, downloaded=100, size=500, dlspeed=0)
        return item | changes

    def observe_for(self, torrent, seconds):
        observations = {}
        for now in range(0, seconds + 1, 60):
            observations, stalled = watch.observe([torrent], observations, now)
        return observations, stalled

    def test_stalled_transfer_frees_slot_after_fifteen_minutes(self):
        self.assertEqual(self.observe_for(self.torrent(), 840)[1], [])
        self.assertEqual(self.observe_for(self.torrent(), 900)[1], ['a' * 40])

    def test_metadata_without_progress_is_also_retained(self):
        self.assertEqual(self.observe_for(self.torrent(state='metaDL', size=0, progress=0), 900)[1], ['a' * 40])

    def test_new_bytes_restart_timeout(self):
        previous, _ = self.observe_for(self.torrent(), 840)
        _, stalled = watch.observe([self.torrent(downloaded=101)], previous, 900)
        self.assertEqual(stalled, [])

    def test_queue_pause_and_finished_files_are_never_stopped(self):
        for state in ['queuedDL', 'stoppedDL', 'pausedDL', 'checkingDL', 'uploading']:
            self.assertEqual(self.observe_for(self.torrent(state=state), 1200), ({}, []))
        self.assertEqual(self.observe_for(self.torrent(progress=1), 1200), ({}, []))

    def test_downtime_does_not_count_as_stall(self):
        previous, _ = self.observe_for(self.torrent(), 600)
        _, stalled = watch.observe([self.torrent()], previous, 3600)
        self.assertEqual(stalled, [])

    def test_api_pauses_and_tags_only_stalled_synthetic_torrent(self):
        torrent = self.torrent()
        with tempfile.TemporaryDirectory(dir='/mnt/dados/lab/state') as directory:
            root = Path(directory)
            cfg = root / 'credentials.json'
            cfg.write_text(json.dumps({'qbit': {'url': 'http://synthetic.invalid', 'password': 'test'}}))
            (root / 'observations.json').write_text(json.dumps({torrent['hash']: {
                'progress': [100, 0.2, 500], 'since': time.time() - 1000, 'seen': time.time() - 60}}))
            response = Mock(text='Ok.')
            response.json.return_value = [torrent]
            session = Mock(headers={})
            session.get.return_value = response
            session.post.return_value = response
            with patch.object(watch, 'STATE', root), patch.object(watch, 'Path', return_value=cfg), \
                    patch.object(watch.requests, 'Session', return_value=session):
                watch.main()
            routes = [call.args[0].rsplit('/api/v2/', 1)[-1] for call in session.post.call_args_list]
            self.assertEqual(routes, ['auth/login', 'torrents/addTags', 'torrents/stop'])
            self.assertEqual(session.post.call_args_list[1].kwargs['data']['tags'], 'erro-sem-progresso')
            self.assertEqual(json.loads((root / 'observations.json').read_text()), {})


if __name__ == '__main__':
    unittest.main()
