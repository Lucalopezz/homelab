#!/usr/bin/env python3
"""Testa retomada da conferência usando somente mídia sintética."""
import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import MagicMock, patch


class ExportCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.library = root / 'biblioteca'
        self.state = root / 'state'
        self.clam = root / 'clamav'
        for directory in (self.library / 'filmes', self.library / 'series', self.library / '.publicacao', self.state, self.clam):
            directory.mkdir(parents=True)
        (self.clam / 'daily.cvd').write_bytes(b'assinatura sintetica')
        self.files = [self.library / 'filmes' / 'a.mp4', self.library / 'filmes' / 'b.mp4']
        for index, p in enumerate(self.files):
            p.write_bytes(b'video sintetico ' + bytes([index]))
        self.db = root / 'triage.sqlite3'
        c = sqlite3.connect(self.db)
        c.execute('create table items(status text, details text)')
        c.execute('insert into items values (?,?)', ('aprovado', json.dumps({'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.files}})))
        c.commit(); c.close()
        self.calls = []
        def open_source(p):
            self.calls.append(p.name)
            return os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        fake = types.SimpleNamespace(RAW=self.library, VIDEO={'.mp4'}, SUBTITLE={'.srt'}, MAX_BYTES=4096,
            safe_parts=lambda s: PurePosixPath(s).parts, open_source=open_source,
            stamp=lambda s: (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns),
            Rejected=ValueError, Review=ValueError, now=lambda: '2026-11-03T00:00:00+00:00')
        path = Path(__file__).with_name('export-manifest.py')
        spec = importlib.util.spec_from_file_location('test_export_manifest', path)
        self.mod = importlib.util.module_from_spec(spec)
        dependency = MagicMock()
        with patch('importlib.util.spec_from_file_location', return_value=dependency), patch('importlib.util.module_from_spec', return_value=fake):
            spec.loader.exec_module(self.mod)
        self.mod.ROOT, self.mod.STATE, self.mod.TRIAGE_DB, self.mod.CLAMAV_DB = self.library, self.state, self.db, self.clam

    def tearDown(self):
        self.tmp.cleanup()

    def test_interrupt_preserves_checkpoint_and_resumes_without_rehash(self):
        manifest = self.library / '.publicacao' / 'manifest.json'
        manifest.write_text('{"original": true}')
        real = self.mod.checkpoint_cache
        writes = []
        def interrupt_second(path, data):
            writes.append(1)
            if len(writes) == 2:
                raise RuntimeError('interrupção simulada')
            real(path, data)
        with patch.object(self.mod, 'checkpoint_cache', side_effect=interrupt_second):
            with self.assertRaisesRegex(RuntimeError, 'interrupção simulada'):
                self.mod.main()
        self.assertEqual(json.loads(manifest.read_text()), {'original': True})
        cache = json.loads((self.state / 'cache.json').read_text())
        self.assertEqual(set(cache), {'filmes/a.mp4'})
        self.calls.clear()
        self.mod.main()
        self.assertEqual(self.calls.count('a.mp4'), 2)  # stat e reconferência, sem reabrir para hash
        self.assertEqual(self.calls.count('b.mp4'), 3)  # inclui leitura para hash
        self.assertEqual(len(json.loads(manifest.read_text())['files']), 2)

    def test_changed_file_is_not_reused_or_published_without_approval(self):
        self.mod.main()
        self.files[0].write_bytes(b'outro conteudo sintetico')
        self.mod.main()
        manifest = json.loads((self.library / '.publicacao' / 'manifest.json').read_text())
        self.assertEqual([x['path'] for x in manifest['files']], ['filmes/b.mp4'])
        report = json.loads((self.state / 'report.json').read_text())
        self.assertEqual(report['held'][0]['path'], 'filmes/a.mp4')

    def test_failed_atomic_replace_preserves_existing_cache(self):
        path = self.state / 'cache.json'
        path.write_text('{"anterior": true}')
        with patch.object(self.mod.os, 'replace', side_effect=OSError('falha simulada')):
            with self.assertRaises(OSError):
                self.mod.checkpoint_cache(path, {'novo': True})
        self.assertEqual(json.loads(path.read_text()), {'anterior': True})
        self.assertEqual(list(self.state.glob('.cache-*')), [])

    def test_new_signature_requires_rechecking_files(self):
        self.mod.main()
        self.calls.clear()
        signature = self.clam / 'daily.cvd'
        st = signature.stat()
        os.utime(signature, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        self.mod.main()
        self.assertEqual(self.calls.count('a.mp4'), 3)
        self.assertEqual(self.calls.count('b.mp4'), 3)


if __name__ == '__main__':
    unittest.main()
