"""Testes de barreiras de arquivo: links, travessia, FIFO e limites de análise."""
import importlib.util
from pathlib import Path
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

spec = importlib.util.spec_from_file_location('triage', Path(__file__).with_name('triage.py'))
triage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage)

class FileBarrierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir='/mnt/dados/lab/state')
        self.root = Path(self.temporary.name)
        self.raw = self.root/'raw'
        self.raw.mkdir()
        triage.RAW = self.raw
        self.outside = self.root/'outside'
        self.outside.mkdir()
        (self.outside/'private.txt').write_text('não deve ser copiado')

    def tearDown(self):
        self.temporary.cleanup()

    def test_file_symlink_is_rejected(self):
        (self.raw/'video.mkv').symlink_to(self.outside/'private.txt')
        with self.assertRaises(OSError):
            triage.open_source(self.raw/'video.mkv')

    def test_directory_symlink_is_rejected(self):
        (self.raw/'show').symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(OSError):
            triage.open_source(self.raw/'show/private.txt')

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(triage.Rejected):
            triage.open_source(self.raw/'../outside/private.txt')

    def test_fifo_does_not_block_or_get_copied(self):
        os.mkfifo(self.raw/'video.mkv')
        with self.assertRaises(triage.Rejected):
            triage.open_source(self.raw/'video.mkv')

    def test_file_above_scan_limit_is_not_released(self):
        source = self.raw/'large.mkv'
        with source.open('wb') as handle:
            handle.truncate(triage.MAX_BYTES+1)
        with self.assertRaises(triage.Review):
            triage.copy_source(source, self.root/'copy.mkv')
        self.assertFalse((self.root/'copy.mkv').exists())

    def test_copy_has_its_own_inode(self):
        source = self.raw/'video.mkv'
        source.write_bytes(b'conteudo de teste')
        destination = self.root/'copy.mkv'
        triage.copy_source(source, destination)
        source.write_bytes(b'origem alterada depois da copia')
        self.assertEqual(destination.read_bytes(), b'conteudo de teste')
        self.assertNotEqual(source.stat().st_ino, destination.stat().st_ino)

class StatusTests(unittest.TestCase):
    def test_reviewed_item_restores_label_without_scanning_again(self):
        pipeline = triage.Pipeline.__new__(triage.Pipeline)
        pipeline.db = sqlite3.connect(':memory:')
        self.addCleanup(pipeline.db.close)
        pipeline.db.execute('CREATE TABLE items (hash TEXT PRIMARY KEY, status TEXT, details TEXT, updated TEXT)')
        key = 'a' * 40
        pipeline.db.execute('INSERT INTO items VALUES (?,?,?,?)', (key, 'revisao', '{}', 'now'))
        pipeline.tag = Mock()
        pipeline._process_locked({'hash': key, 'tags': 'triagem-pendente'})
        pipeline.tag.assert_called_once_with(key, 'triagem-revisao')
        self.assertEqual(pipeline.db.execute('SELECT status FROM items').fetchone()[0], 'revisao')
        pipeline.tag.reset_mock()
        pipeline._process_locked({'hash': key, 'tags': 'triagem-revisao'})
        pipeline.tag.assert_not_called()


class ScannerQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir='/mnt/dados/lab/state')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'clamav-scan.lock').touch()
        self.state_patch = patch.object(triage, 'STATE', self.root)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def test_parallel_clients_wait_outside_scanner_timeout(self):
        guard = threading.Lock()
        running, peak = 0, 0

        def scanner(*args, **kwargs):
            nonlocal running, peak
            self.assertGreater(kwargs['timeout'], 1200)
            with guard:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with guard:
                running -= 1
            return subprocess.CompletedProcess([], 0, '', '')

        with patch.object(triage.subprocess, 'run', side_effect=scanner):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(triage.scan, [self.root / 'a.mp4', self.root / 'b.mp4']))
        self.assertEqual(peak, 1)

    def test_timeout_still_refuses_approval(self):
        with patch.object(triage.subprocess, 'run', side_effect=subprocess.TimeoutExpired('clamdscan', 1260)):
            with self.assertRaisesRegex(RuntimeError, 'arquivo não liberado'):
                triage.scan(self.root / 'video.mp4')


if __name__ == '__main__':
    unittest.main()
