"""Regression gate for NAS and test-host provisioning scripts."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ("setup-nas.sh", "install-ubuntu26.sh", "install-streaming.sh",
         "install-requests.sh", "install-loggen.sh", "deploy-test-system.sh", "one-shot-install.sh",
         "install-station-utilities.sh", "finish-complete.sh", "install-control-center.sh")


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
        self.assertIn("bash tools/install-control-center.sh", deployer)

    def test_streaming_package_lock_wait_is_non_destructive(self):
        script = (ROOT / "tools" / "install-streaming.sh").read_text()
        self.assertIn("DPkg::Lock::Timeout=300", script)
        self.assertIn("DEBIAN_FRONTEND=noninteractive", script)
        self.assertIn("glasscoder jack-tools jackd2 jack-example-tools", script)
        self.assertIn("for program in glasscoder jack_lsp jack_connect jack_disconnect", script)
        self.assertNotIn("apt-get update", script.split("sudo -v", 1)[1])
        self.assertNotIn("rm -f /var/lib/dpkg/lock", script)
        self.assertNotIn("kill -9", script)
        self.assertIn("if systemctl --user daemon-reload; then", script)
        self.assertIn("--skip-dependencies", script)
        self.assertIn("all_installed", script)
        self.assertIn("jack-example-tools", script)
        self.assertIn("User systemd manager unavailable", script)

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

    def test_finish_staging_does_not_rebuild_or_overwrite_data(self):
        script = (ROOT / "tools" / "finish-complete.sh").read_text()
        self.assertIn('bash "$ROOT/tools/install-station-utilities.sh"', script)
        self.assertIn('bash "$ROOT/tools/install-streaming.sh"', script)
        self.assertIn('bash "$ROOT/tools/install-requests.sh"', script)
        self.assertIn('bash "$ROOT/tools/install-loggen.sh"', script)
        self.assertIn('install -m 0644 "$source_path"', script)
        self.assertIn('fuser -s /var/lib/dpkg/lock-frontend', script)
        self.assertIn('jack-example-tools', script)
        self.assertIn('--no-packages', script)
        self.assertIn("sudo -n mariadb -NBe", script)
        self.assertIn("Rivendell.GROUPS", script)
        self.assertIn("Rivendell.SERVICES", script)
        self.assertIn("--skip-dependencies", script)
        self.assertIn('bash "$ROOT/tools/install-control-center.sh"', script)
        self.assertIn('"$ROOT/tools/install-control-center.sh" --no-packages', script)
        self.assertNotIn('dpkg-buildpackage', script)
        self.assertNotIn('apt-get install', script)
        self.assertNotIn('mariadb -e', script)
        self.assertNotIn('systemctl enable', script)
        self.assertNotIn('tmux', script)
        self.assertNotIn('rm -rf', script)

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
