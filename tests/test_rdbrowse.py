"""NAS discovery and mounted-folder security regressions."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import rdbrowse
import rdsourcefolders


class BrowseTests(unittest.TestCase):
    def test_smb_share_filter(self):
        output = ("Disk|MUSIC|Active albums\nDisk|JINGLES|Production\n"
                  "IPC|IPC$|No\nPrinter|HP|Printer\nDisk|Music Archive|Archive\n"
                  "Disk|MUSIC|Duplicate\n")
        shares = rdbrowse.parse_smb_shares(output)
        self.assertEqual([r["name"] for r in shares],
                         ["MUSIC", "JINGLES", "Music Archive"])
        self.assertEqual([r["mountable"] for r in shares], [True, True, False])

    def test_underscored_share_and_trailing_slash_are_valid(self):
        self.assertEqual(rdbrowse.share_name("U1000/"), "U1000")
        self.assertEqual(rdbrowse.share_name("RADIO_BROADCASTING/"), "RADIO_BROADCASTING")
        self.assertEqual(rdbrowse.share_name("Radio_Jingles"), "Radio_Jingles")
        shares = rdbrowse.parse_smb_shares(
            "Disk|RADIO_BROADCASTING|Library\\nDisk|U1000|User music\\n")
        self.assertEqual([x["mountable"] for x in shares], [True, True])
        for invalid in ("RADIO_BROADCASTING/Albums", "music;malicious", "../bad", ""):
            with self.subTest(invalid=invalid), self.assertRaises(rdbrowse.BrowseError):
                rdbrowse.share_name(invalid)

    def test_trailing_slash_normalization_reaches_smbclient(self):
        with patch.object(rdbrowse, "command", return_value="") as run:
            rdbrowse.discover("smb", "192.168.0.146", "folders",
                              share="RADIO_BROADCASTING/",
                              folder="Music/Gold_Hits",
                              auth=("user", "example-only"))
        argv = run.call_args.args[0]
        self.assertIn("//192.168.0.146/RADIO_BROADCASTING", argv)
        self.assertNotIn("//192.168.0.146/RADIO_BROADCASTING/", argv)
        self.assertEqual(argv[argv.index("-D") + 1], "Music/Gold_Hits")

    def test_smb_folder_parser_never_exposes_files(self):
        data = ("  .                                   D        0  Mon Nov  2 20:00:00 2026\n"
                "  ..                                  D        0  Mon Nov  2 20:00:00 2026\n"
                "  Power                               D        0  Mon Nov  2 20:00:00 2026\n"
                "  Gold Hits                           D        0  Mon Nov  2 20:00:00 2026\n"
                "  bad.mp3                             A    15000  Mon Nov  2 20:00:00 2026\n")
        self.assertEqual(rdbrowse.parse_smb_folders(data), ["Gold Hits", "Power"])

    def test_nfs_exports_and_invalid_paths(self):
        data = "Export list for 192.168.0.146:\n/export/music *(ro)\n/other/path 192.168.0.0/24\n/../unsafe *\n"
        got = rdbrowse.parse_nfs_exports(data)
        self.assertEqual([x["name"] for x in got], ["/export/music", "/other/path"])
        for value in ("../music", "Music/../backup", "/absolute", "Artist\nName", "A\\B"):
            with self.subTest(value=value), self.assertRaises(rdbrowse.BrowseError):
                rdbrowse.folder_path(value)

    def test_credentials_are_not_in_command_arguments(self):
        calls = []
        def runner(arguments):
            calls.append(arguments)
            self.assertNotIn("private-secret", " ".join(arguments))
            auth_path = Path(arguments[arguments.index("-A") + 1])
            self.assertEqual(auth_path.stat().st_mode & 0o077, 0)
            self.assertIn("password = private-secret", auth_path.read_text())
            return "Disk|Music|Tracks\n"
        with patch.object(rdbrowse, "command", side_effect=runner):
            with patch.object(rdbrowse, "smb_auth", wraps=rdbrowse.smb_auth) as auth:
                result = rdbrowse.discover("smb", "192.168.0.146", "shares",
                                           auth=("example-user", "private-secret"))
        self.assertEqual(result["shares"][0]["name"], "Music")
        self.assertEqual(len(calls), 1)
        self.assertEqual(auth.call_count, 1)
        self.assertFalse(Path(calls[0][calls[0].index("-A") + 1]).exists())

    def test_source_folder_browser_is_read_only_and_bounds_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "radio-music"
            (base / "current" / "Music" / "Gold").mkdir(parents=True)
            (base / "current" / "Music" / "Power").mkdir()
            (base / "current" / "Music" / "track.mp3").write_bytes(b"unchanged")
            outside = Path(temp) / "other"
            outside.mkdir()
            (base / "current" / "escape").symlink_to(outside)
            inventory = [{"name": "current", "mounted": True,
                          "readonly": True, "legacy": False}]
            contents = rdsourcefolders.folders("current", "Music",
                                               inventory=inventory, root=base)
            self.assertEqual(contents["folders"], ["Gold", "Power"])
            for path in ("../", "escape", "Music/../../../"):
                with self.subTest(path=path), self.assertRaises(rdsourcefolders.FolderError):
                    rdsourcefolders.folders("current", path, inventory=inventory, root=base)
            self.assertEqual((base / "current" / "Music" / "track.mp3").read_bytes(), b"unchanged")

    def test_offline_source_cannot_be_browsed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(rdsourcefolders.FolderError):
                rdsourcefolders.resolve_folder(
                    "offline", "", inventory=[{"name": "offline", "mounted": False,
                                                "readonly": False, "legacy": False}],
                    root=root)


if __name__ == "__main__":
    unittest.main()
