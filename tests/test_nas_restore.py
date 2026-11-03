"""Boot recovery is read-only, bounded, and does not fabricate missing NAS mounts."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import rdcomplete_nas_restore as recover


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.base = Path(self.td.name) / "radio-music"
        self.base.mkdir()
        self.fstab = Path(self.td.name) / "fstab"

    def test_empty_configuration_does_not_create_a_mount(self):
        self.fstab.write_text("UUID=other / ext4 defaults 0 1\n")
        self.assertEqual(recover.refresh(self.fstab, self.base), (0, 0))
        self.assertEqual(list(self.base.iterdir()), [])

    def test_read_only_nested_source_restores_only_expected_export(self):
        target = self.base / "songs"
        target.mkdir()
        self.fstab.write_text(
            f"server:/exports/music {target} nfs ro,_netdev,x-systemd.automount 0 0\n")
        observed = []
        def fake_run(args, timeout):
            observed.append(args)
            return True
        class Result:
            returncode = 0
            stdout = "server:/exports/music nfs4 ro,hard,relatime\n"
        with patch.object(recover, "run", side_effect=fake_run), \
             patch.object(recover.subprocess, "run",
                          side_effect=lambda args, **kwargs:
                          type("R", (), {"returncode": 0, "stdout":
                          "mnt-radio\\x2dmusic-songs.automount\n"} if
                          "systemd-escape" in args[0] else
                          {"returncode": 0, "stdout": Result.stdout})()):
            ok, failed = recover.refresh(self.fstab, self.base)
        self.assertEqual((ok, failed), (1, 0))
        self.assertTrue(any("/usr/bin/stat" in args for args in observed))
        self.assertTrue(any(str(target) + "/." in args for args in observed))

    def test_writable_or_symlinked_source_fails_closed(self):
        target = self.base / "archive"
        target.mkdir()
        self.fstab.write_text(f"//server/Archive {target} cifs rw,_netdev 0 0\n")
        self.assertEqual(recover.refresh(self.fstab, self.base), (0, 1))
        target.rmdir()
        target.symlink_to(Path(self.td.name))
        self.fstab.write_text(f"//server/Archive {target} cifs ro,_netdev 0 0\n")
        self.assertEqual(recover.refresh(self.fstab, self.base), (0, 1))

    def test_service_persists_after_boot_and_retries(self):
        service = (ROOT / "systemd/rdcomplete-nas-restore.service").read_text()
        timer = (ROOT / "systemd/rdcomplete-nas-restore.timer").read_text()
        installer = (ROOT / "tools/install-control-center.sh").read_text()
        self.assertIn("After=network-online.target", service)
        self.assertIn("OnBootSec=35s", timer)
        self.assertIn("OnUnitInactiveSec=120s", timer)
        self.assertIn("systemctl enable --now rdcomplete-nas-restore.timer", installer)
        self.assertNotIn("systemctl restart rivendell", service)
        self.assertNotIn("rm -rf", service)


if __name__ == "__main__":
    unittest.main()
