#!/usr/bin/env python3
"""Test quarantine fallback using only temporary synthetic files."""

import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jellyfin import sync


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "library" / "series" / "Sample"
        self.quarantine = self.root / "state" / "quarentena"
        self.source_dir.mkdir(parents=True)
        self.quarantine.mkdir(parents=True)
        self.source = self.source_dir / "sample.mkv"
        self.source.write_bytes(b"synthetic media bytes\0" * 4096)

    def tearDown(self):
        self.temp.cleanup()

    def force_cross_device(self):
        real_replace = sync.os.replace

        def replace(source, destination):
            if Path(source) == self.source and Path(destination).parent == self.quarantine:
                raise OSError(errno.EXDEV, "synthetic cross-device rename")
            return real_replace(source, destination)

        return replace

    def test_cross_device_fallback_copies_verifies_then_removes_source(self):
        expected_stamp = sync.file_stamp(self.source)
        with patch.object(sync.os, "replace", side_effect=self.force_cross_device()):
            held = sync.quarantine_file(
                self.source,
                self.quarantine,
                "series/Sample/sample.mkv",
                expected_stamp,
            )

        self.assertFalse(self.source.exists())
        self.assertEqual(held.read_bytes(), b"synthetic media bytes\0" * 4096)
        self.assertEqual(list(self.quarantine.iterdir()), [held])

    def test_changed_source_is_preserved(self):
        expected_stamp = sync.file_stamp(self.source)
        self.source.write_bytes(b"changed synthetic bytes")

        with self.assertRaisesRegex(ValueError, "mudou desde"):
            sync.quarantine_file(
                self.source,
                self.quarantine,
                "series/Sample/sample.mkv",
                expected_stamp,
            )

        self.assertTrue(self.source.exists())
        self.assertEqual(list(self.quarantine.iterdir()), [])

    def test_quarantine_collision_preserves_source(self):
        stat = self.source.stat()
        held = self.quarantine / (
            sync.hashlib.sha256(b"series/Sample/sample.mkv").hexdigest()
            + f"-{stat.st_mtime_ns}-{stat.st_ino}"
        )
        held.write_bytes(b"different archived file")

        with patch.object(sync.os, "replace", side_effect=self.force_cross_device()):
            with self.assertRaises(FileExistsError):
                sync.quarantine_file(
                    self.source,
                    self.quarantine,
                    "series/Sample/sample.mkv",
                    sync.file_stamp(self.source),
                )

        self.assertTrue(self.source.exists())
        self.assertEqual(held.read_bytes(), b"different archived file")
        self.assertEqual(len(list(self.quarantine.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
