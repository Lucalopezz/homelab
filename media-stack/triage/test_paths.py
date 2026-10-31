"""Testes de barreiras de arquivo: links, travessia, FIFO e limites de análise."""
import importlib.util
from pathlib import Path
import os
import tempfile
import unittest

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

if __name__ == '__main__':
    unittest.main()
