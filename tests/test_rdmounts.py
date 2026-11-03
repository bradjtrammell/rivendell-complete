"""Multi-NAS inventory, reference isolation, and source validation."""
from __future__ import annotations

import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import rdmounts
import rdexternal


class MountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "radio-music"
        self.root.mkdir()
        self.fstab = self.base / "fstab"

    def test_safe_named_paths_and_reserved_legacy_name(self):
        self.assertEqual(rdmounts.mount_path("archive"), Path("/mnt/radio-music/archive"))
        for name in ("legacy", "", "../music", "/etc", "A", "one/two", "a.b",
                     " a", "a\nb", "a" * 33):
            with self.subTest(name=name):
                with self.assertRaises(rdmounts.MountError):
                    rdmounts.mount_path(name)

    def test_mixed_protocol_inventory(self):
        self.fstab.write_text(
            "# existing system entries\n"
            "UUID=boot / ext4 defaults 0 1\n"
            "nas1:/export/music " + str(self.root / "current") +
            " nfs ro,_netdev,x-systemd.automount 0 0\n"
            "//nas2/Archive " + str(self.root / "archive") +
            " cifs ro,credentials=/etc/rivendell-complete/nas-archive.cred 0 0\n"
        )
        items = rdmounts.fstab_mounts(self.fstab, self.root)
        self.assertEqual(len(items), 2)
        self.assertEqual([x["name"] for x in items], ["archive", "current"])
        self.assertEqual([x["protocol"] for x in items], ["SMB", "NFS"])
        self.assertTrue(all(x["readonly_configured"] for x in items))
        self.assertTrue(all(not x["legacy"] for x in items))
        self.assertNotIn("password", str(items).lower())

    def test_source_input_rejects_shell_fstab_injection(self):
        rdmounts.validate_source("nfs", "storage:/music/radio")
        rdmounts.validate_source("smb", "//storage/radio")
        for protocol, path in (
            ("nfs", "server:/share\nfake /etc ext4 rw 0 0"),
            ("nfs", "server:/music options"),
            ("smb", "//nas/music,credentials=/tmp/exposed"),
            ("smb", "//nas/music\\x"),
            ("ssh", "nas:/music"),
        ):
            with self.subTest(protocol=protocol, path=path):
                with self.assertRaises(rdmounts.MountError):
                    rdmounts.validate_source(protocol, path)

    def test_legacy_mount_is_distinct_and_nested_legacy_is_not_accepted(self):
        self.fstab.write_text(
            "server:/original " + str(self.root) + " nfs ro 0 0\n"
            "server:/evil " + str(self.root / "legacy") + " nfs ro 0 0\n"
        )
        items = rdmounts.fstab_mounts(self.fstab, self.root)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["legacy"])

    def test_duplicate_name_aborts_inventory(self):
        self.fstab.write_text(
            "a:/one " + str(self.root / "one") + " nfs ro 0 0\n"
            "b:/two " + str(self.root / "one") + " nfs ro 0 0\n"
        )
        with self.assertRaises(rdmounts.MountError):
            rdmounts.fstab_mounts(self.fstab, self.root)

    def test_mount_status_displays_offline_instead_of_fake_success(self):
        self.fstab.write_text(
            "nas:/music " + str(self.root / "current") + " nfs ro 0 0\n"
        )
        with patch.object(rdmounts, "mounted_details",
                          return_value=("", "", False)):
            with patch.object(rdmounts.subprocess, "run"):
                rows = rdmounts.mount_inventory(self.fstab, self.root)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["mounted"])
        self.assertFalse(rows[0]["readonly"])

    def test_per_share_reference_namespaces_no_duplicate_file_collision(self):
        # Two independent shares may contain the SAME relative track name.
        for name in ("current", "archive"):
            folder = self.root / name / "Artist"
            folder.mkdir(parents=True)
            track = folder / "Track.wav"
            with wave.open(str(track), "wb") as dst:
                dst.setnchannels(2)
                dst.setsampwidth(2)
                dst.setframerate(48000)
                dst.writeframes(b"\0" * 4 * 48000)
        refs = self.base / "refs"
        rdexternal.write_reference(refs, "100101_001", "current/Artist/Track.wav")
        rdexternal.write_reference(refs, "100102_001", "archive/Artist/Track.wav")
        mappings = rdexternal.references(refs)
        self.assertEqual(mappings["current/Artist/Track.wav"], 100101)
        self.assertEqual(mappings["archive/Artist/Track.wav"], 100102)
        self.assertEqual(len(mappings), 2)
        self.assertEqual(
            rdexternal.media_path(self.root, "archive/Artist/Track.wav"),
            self.root / "archive" / "Artist" / "Track.wav")

    def test_import_preview_excludes_only_selected_share_references(self):
        for name in ("current", "archive"):
            folder = self.root / name
            folder.mkdir()
            with wave.open(str(folder / "Music.wav"), "wb") as dst:
                dst.setnchannels(1)
                dst.setsampwidth(2)
                dst.setframerate(48000)
                dst.writeframes(b"\0" * 2 * 48000)
        refs = self.base / "refs"
        rdexternal.write_reference(refs, "100001_001", "current/Music.wav")
        result = io.StringIO()
        with redirect_stdout(result):
            status = rdexternal.main([
                "--root", str(self.root / "archive"), "--refs", str(refs),
                "--group", "MUSIC", "--reference-prefix", "archive"])
        self.assertEqual(status, 0)
        self.assertIn("SCAN new=1", result.getvalue())
        self.assertEqual(rdexternal.references(refs), {"current/Music.wav": 100001})

    def test_root_helper_source_validation_matches_mount_model(self):
        spec = importlib.util.spec_from_file_location(
            "rdcomplete_root_test", ROOT / "tools" / "rdcomplete_root.py")
        helper = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = helper
        spec.loader.exec_module(helper)
        self.assertIsNone(helper.validate_source("nfs", "server:/music"))
        with self.assertRaises(helper.CommissionError):
            helper.validate_source("smb", "//bad/share,uid=0")


if __name__ == "__main__":
    unittest.main()
