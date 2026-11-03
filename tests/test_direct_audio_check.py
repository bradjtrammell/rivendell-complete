"""Direct NAS playback audit never mutates source music or imported cuts."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import rdcomplete_direct_audio_check as direct


class DirectAudioChecks(unittest.TestCase):
    def test_mismatched_runtime_configuration_fails_before_db(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "rd.conf"
            config.write_text("[ExternalAudio]\nRoot=/elsewhere\nReferences=/tmp/refs\n")
            with self.assertRaises(direct.DiagnosticError):
                direct.diagnose(config=config)

    def test_offline_sources_fail_without_touching_database(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config = base / "rd.conf"
            root = base / "music"
            refs = base / "refs"
            config.write_text(f"[ExternalAudio]\nRoot={root}\nReferences={refs}\n")
            with patch.object(direct, "mount_inventory", return_value=[
                {"name": "nas_source", "mounted": False, "readonly": False}
            ]):
                result = direct.diagnose(root=root, refs=refs, config=config)
            self.assertEqual(result["status"], "blocked_nas_offline")
            self.assertEqual(result["offline_or_writable_mounts"], ["nas_source"])
            self.assertEqual(result["referenced_carts"], 0)

    def test_unconfigured_sources_do_not_get_fabricated(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config = base / "rd.conf"
            root = base / "music"
            refs = base / "refs"
            config.write_text(f"[ExternalAudio]\nRoot={root}\nReferences={refs}\n")
            with patch.object(direct, "mount_inventory", return_value=[]):
                with self.assertRaises(direct.DiagnosticError):
                    direct.diagnose(root=root, refs=refs, config=config)


if __name__ == "__main__":
    unittest.main()
