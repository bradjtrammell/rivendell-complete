"""Regression gate for NAS and test-host provisioning scripts."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ("setup-nas.sh", "install-ubuntu26.sh", "install-streaming.sh",
         "install-requests.sh", "install-loggen.sh", "deploy-test-system.sh", "one-shot-install.sh",
         "install-station-utilities.sh")


class ProvisioningTests(unittest.TestCase):
    def test_installers_pass_bash_syntax(self):
        paths = [str(ROOT / "tools" / name) for name in FILES]
        p = subprocess.run(["bash", "-n", *paths], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_help_without_privileged_actions(self):
        for name in ("setup-nas.sh", "deploy-test-system.sh"):
            with self.subTest(name=name):
                p = subprocess.run(["bash", str(ROOT/"tools"/name), "--help"],
                                   capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("read-only", p.stdout.lower())

    def test_nas_fstab_and_credential_safety(self):
        s = (ROOT / "tools/setup-nas.sh").read_text()
        self.assertEqual(s.count("#!/usr/bin/env bash"), 1)
        self.assertEqual(s.count("apt-get update"), 2)
        for fragment in ("flock -n 9", "written_sha", "mountpoint -q",
                         "findmnt -rn -T", "chmod 0600", "ro,credentials="):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, s)

    def test_one_shot_installer_safe_entrypoint(self):
        p = subprocess.run(["bash", str(ROOT / "tools" / "one-shot-install.sh"), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("foreground", p.stdout)
        s = (ROOT / "tools" / "one-shot-install.sh").read_text()
        for marker in ("sudo -v", "git merge --ff-only origin/dev",
                       "--install --streaming --jobs 2", "INSTALLATION FAILED"):
            self.assertIn(marker, s)
        self.assertNotIn("git clean -", s)
        self.assertNotIn("git reset --hard", s)
        self.assertNotIn("tmux", s)
        self.assertNotIn("nohup", s)
        self.assertIn("--install-existing --streaming --jobs 2", s)
        self.assertIn("rdcomplete-jack-route", s)
        self.assertIn("rdlogmanager rdlogedit rdpanel", s)
        self.assertIn("rdcomplete-stationplan", s)
        self.assertIn("rdcomplete-live-requests", s)

    def test_staged_utilities_never_start_live_services(self):
        installer = (ROOT / "tools" / "install-station-utilities.sh").read_text()
        self.assertIn('install -m 0755 "$source_path"', installer)
        self.assertIn('"$BIN/rdcomplete-$name"', installer)
        self.assertNotIn("systemctl enable", installer)
        self.assertNotIn("sudo ", installer)
        deployer = (ROOT / "tools" / "deploy-test-system.sh").read_text()
        self.assertIn("bash tools/install-station-utilities.sh", deployer)

    def test_package_resume_and_reauth(self):
        installer = (ROOT / "tools" / "install-ubuntu26.sh").read_text()
        deployer = (ROOT / "tools" / "deploy-test-system.sh").read_text()
        systemd = (ROOT / "systemd" / "Makefile.am").read_text()
        for marker in ("--install-existing", "REUSE_PACKAGES=1", "sudo -v || fail", "sudo -n apt-get -s install"):
            self.assertIn(marker, installer)
        self.assertIn("--install-existing", deployer)
        self.assertIn("RESUME_STAGED=1", installer)
        self.assertIn("table_count == 0", installer)
        self.assertIn("rdcomplete-first-install", installer)
        self.assertIn("preserving both and skipping reinstallation", installer)
        self.assertIn("Unrecognized partial Rivendell installation", installer)
        self.assertNotIn("Existing Rivendell configuration found", installer)
        one_shot = (ROOT / "tools" / "one-shot-install.sh").read_text()
        self.assertNotIn("Rivendell configuration exists. Refusing", one_shot)
        self.assertIn('test -z "$(DESTDIR)"', systemd)

    def test_safe_deployer_default(self):
        s = (ROOT / "tools/deploy-test-system.sh").read_text()
        self.assertIn("mode=check", s)
        self.assertIn("python3 -m unittest discover", s)
        self.assertIn('if [[ "$mode" == check ]]; then', s)
        test_line = s.index("python3 -m unittest discover")
        check_line = s.index('if [[ "$mode" == check ]]; then')
        self.assertGreater(test_line, check_line)
        self.assertIn("skipping development tests during installation", s)
        self.assertIn("NOT air-qualified", s)


if __name__ == "__main__":
    unittest.main()
