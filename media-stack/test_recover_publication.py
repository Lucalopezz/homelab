"""Recuperação com arquivos sintéticos: integridade, concorrência e links."""
import hashlib
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('recovery', Path(__file__).with_name('recover-publication.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/mnt/dados/lab/state')
        self.root = Path(self.temp.name)
        self.source = self.root / 'approved'
        self.source.mkdir()
        self.library = self.root / 'library'
        self.target = self.library / 'series/show/video.mkv'
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'partial')
        os.utime(self.target, (1, 1))
        self.content = b'complete synthetic media' * 50
        (self.source / 'video.mkv').write_bytes(self.content)
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.old_library = r.LIBRARY
        r.LIBRARY = self.library

    def tearDown(self):
        r.LIBRARY = self.old_library
        self.temp.cleanup()

    def repair(self, digest=None):
        return r.repair_copy(self.source, 'video.mkv', digest or self.digest,
                             'series/show/video.mkv')

    def test_verified_copy_atomically_replaces_partial_and_preserves_it(self):
        result = self.repair()
        self.assertEqual(self.target.read_bytes(), self.content)
        self.assertEqual(Path(result['partial_preserved']).read_bytes(), b'partial')
        self.assertFalse(list(self.target.parent.glob('.recuperando-*')))

    def test_failed_integrity_keeps_original_and_removes_temporary(self):
        with self.assertRaises(ValueError):
            self.repair('0' * 64)
        self.assertEqual(self.target.read_bytes(), b'partial')
        self.assertFalse(list(self.target.parent.glob('.recuperando-*')))

    def test_concurrent_import_is_not_overwritten(self):
        original = r.verified_copy
        def concurrent(*args):
            original(*args)
            self.target.write_bytes(b'new concurrent import')
        with patch.object(r, 'verified_copy', side_effect=concurrent):
            with self.assertRaises(ValueError):
                self.repair()
        self.assertEqual(self.target.read_bytes(), b'new concurrent import')

    def test_symlink_source_and_parent_traversal_are_refused(self):
        (self.source / 'link.mkv').symlink_to(self.target)
        with self.assertRaises(OSError):
            r.verified_copy(self.source, 'link.mkv', self.digest)
        with self.assertRaises(ValueError):
            r.verified_copy(self.source, '../library/series/show/video.mkv', self.digest)

    def recovery_fixture(self, expected):
        state = self.root / 'state'
        state.mkdir()
        public = self.root / 'public'
        key = 'a' * 40
        dest = public / 'series' / ('pack__' + key[:8])
        dest.mkdir(parents=True)
        (dest / 'video.mkv').write_bytes(self.content)
        marker = dest / 'TRIAGEM.json'
        marker.write_text(json.dumps({'hash': key, 'scanner': 'ClamAV',
                                     'verified_at': '2026-11-02T10:00:00+00:00',
                                     'torrent': 'synthetic', 'sha256': {'video.mkv': expected}}))
        marker.chmod(0o440)
        db = sqlite3.connect(state / 'state.sqlite3')
        db.execute('CREATE TABLE items (hash TEXT PRIMARY KEY, status TEXT, details TEXT, updated TEXT)')
        db.execute('INSERT INTO items VALUES (?,?,?,?)',
                   (key, 'revisao', json.dumps({'name': 'synthetic', 'reason': r.COLLISION}), 'old'))
        db.commit()
        db.close()
        return state, public, key

    def run_recovery(self, state, public, key):
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with patch.object(r, 'STATE', state), patch.object(r, 'PUBLIC', public), \
             patch.object(r.pwd, 'getpwnam', return_value=account), \
             patch.object(sys, 'argv', ['recover', '--hash', key, '--apply']), \
             contextlib.redirect_stdout(io.StringIO()):
            r.main()

    def test_interrupted_approval_is_recovered_and_previous_reason_preserved(self):
        state, public, key = self.recovery_fixture(self.digest)
        self.run_recovery(state, public, key)
        with sqlite3.connect(state / 'state.sqlite3') as db:
            status, raw = db.execute('SELECT status,details FROM items').fetchone()
        self.assertEqual(status, 'aprovado')
        details = json.loads(raw)
        self.assertEqual(details['files']['video.mkv'], self.digest)
        self.assertEqual(details['recovered_from']['reason'], r.COLLISION)

    def test_changed_approved_copy_does_not_restore_database_record(self):
        state, public, key = self.recovery_fixture('0' * 64)
        with self.assertRaises(ValueError):
            self.run_recovery(state, public, key)
        with sqlite3.connect(state / 'state.sqlite3') as db:
            self.assertEqual(db.execute('SELECT status FROM items').fetchone()[0], 'revisao')


if __name__ == '__main__':
    unittest.main()
