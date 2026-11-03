"""Regression tests for non-destructive native audio materialization."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import rdcomplete_materialize as native


class MaterializeTests(unittest.TestCase):
    def test_native_cut_names_are_deterministic_and_bounded(self):
        store = Path("/var/snd")
        self.assertEqual(native.destination(store, 100001),
                         store / "100001_001.wav")
        for cart in (0, -1, 1000000):
            with self.subTest(cart=cart):
                with self.assertRaises(native.MaterializeError):
                    native.destination(store, cart)

    def test_refuses_to_overwrite_existing_native_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            store = base / "snd"
            store.mkdir()
            track = store / "100001_001.wav"
            track.write_bytes(b"PROTECTED EXISTING AUDIO")
            source = base / "source.mp3"
            source.write_bytes(b"test")
            with self.assertRaises(native.MaterializeError):
                native.convert(source, track, store.stat())
            self.assertEqual(track.read_bytes(), b"PROTECTED EXISTING AUDIO")

    def test_refuses_to_replace_symlinked_audio_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            store = base / "snd"
            store.mkdir()
            link = base / "alias"
            link.symlink_to(store, target_is_directory=True)
            with self.assertRaises(native.MaterializeError):
                native.check_store(link)

    def test_cli_is_dry_run_unless_commit_explicitly_given(self):
        with patch.object(native, "materialize", return_value={
                "missing_sources": 0, "failed": 0}) as perform:
            self.assertEqual(native.main([]), 0)
            perform.assert_called_once_with(commit=False, limit=None)


if __name__ == "__main__":
    unittest.main()
