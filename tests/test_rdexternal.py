"""Tests for read-only external media references and metadata probe."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import wave

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "rdexternal.py"
spec = importlib.util.spec_from_file_location("rdexternal_tested", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ExternalMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "library"
        self.root.mkdir()
        (self.root / "Power").mkdir()
        self.refs = self.base / "refs"
        self.track = self.root / "Power" / "Test Track.wav"
        with wave.open(str(self.track), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(b"\0" * 4 * 48000)

    def test_read_only_path_resolution(self):
        path = module.media_path(self.root, "Power/Test Track.wav")
        self.assertEqual(path, self.track)
        for value in ["../outside.mp3", "/etc/passwd", "Power/../../etc/passwd",
                      "Power\n/Test Track.wav", "Power\\Test Track.wav"]:
            with self.subTest(value=value):
                with self.assertRaises(module.ImportFailure):
                    module.media_path(self.root, value)

    def test_symlink_escape_disallowed(self):
        external = self.base / "outside.wav"
        external.write_bytes(b"x")
        (self.root / "Power" / "escape.wav").symlink_to(external)
        with self.assertRaises(module.ImportFailure):
            module.media_path(self.root, "Power/escape.wav")
        self.assertEqual(list(module.scan_paths(self.root)), ["Power/Test Track.wav"])

    def test_reference_is_immutable_and_recoverable(self):
        ref = module.write_reference(self.refs, "100123_001", "Power/Test Track.wav")
        self.assertEqual(ref.read_bytes(), b"Power/Test Track.wav\n")
        self.assertEqual(module.references(self.refs), {"Power/Test Track.wav": 100123})
        with self.assertRaises(module.ImportFailure):
            module.write_reference(self.refs, "100123_001", "Power/Test Track.wav")
        self.assertEqual(ref.read_bytes(), b"Power/Test Track.wav\n")

    def test_bad_references_rejected(self):
        self.refs.mkdir()
        (self.refs / "100001_001.ref").write_bytes(b"bad\nnewline\n")
        with self.assertRaises(module.ImportFailure):
            module.references(self.refs)

    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe not installed")
    def test_metadata_duration_and_no_original_changes(self):
        before = self.track.read_bytes()
        record = module.probe(self.root, "Power/Test Track.wav")
        self.assertEqual(record.length_ms, 1000)
        self.assertEqual(record.sample_rate, 48000)
        self.assertEqual(record.channels, 2)
        self.assertEqual(record.coding, 0)
        self.assertEqual(record.title, "Test Track")
        self.assertEqual(self.track.read_bytes(), before)

    def test_dry_run_never_writes(self):
        if not shutil.which("ffprobe"):
            self.skipTest("ffprobe not installed")
        original = self.track.read_bytes()
        status = module.main([
            "--root", str(self.root), "--refs", str(self.refs),
            "--group", "POWER", "--limit", "1"])
        self.assertEqual(status, 0)
        self.assertFalse(self.refs.exists())
        self.assertEqual(self.track.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
