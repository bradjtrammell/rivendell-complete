"""Safety and source checks for the native Rivendell Complete operator console."""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile
from unittest.mock import patch
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_helper():
    spec = importlib.util.spec_from_file_location(
        "rdcomplete_root", ROOT / "tools" / "rdcomplete_root.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ControlCenterSafety(unittest.TestCase):
    def test_privileged_source_validation(self):
        module = load_helper()
        for protocol, source in (
            ("nfs", "fileserver:/music/radio"),
            ("smb", "//fileserver/music"),
        ):
            module.validate_source(protocol, source)
        for protocol, source in (
            ("nfs", "server:/music other"),
            ("nfs", "bad;/bin/sh:/path"),
            ("nfs", "server:/../music;echo"),
            ("smb", "//nas/music\nbad"),
            ("smb", "//nas/share,uid=0"),
            ("ftp", "host:/music"),
        ):
            with self.subTest(protocol=protocol, source=source):
                with self.assertRaises(module.CommissionError):
                    module.validate_source(protocol, source)

    def test_helper_requires_root_and_named_actions_only(self):
        p = subprocess.run(
            [sys.executable, str(ROOT / "tools/rdcomplete_root.py"), "scan",
             "--group", "MUSIC"],
            capture_output=True, text=True, timeout=10,
        )
        if hasattr(__import__("os"), "geteuid") and __import__("os").geteuid() != 0:
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("Root privileges required", p.stderr)
        p = subprocess.run(
            [sys.executable, str(ROOT / "tools/rdcomplete_root.py"), "arbitrary-shell"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(p.returncode, 0)

    def test_installer_pins_privileged_scripts_to_root_owned_location(self):
        installer = (ROOT / "tools" / "install-control-center.sh").read_text()
        self.assertIn("/usr/local/libexec/rivendell-complete", installer)
        self.assertIn("sudo install -o root -g root", installer)
        self.assertIn("python3-pyqt5 pkexec", installer)
        self.assertIn("SKIP_PACKAGES=1", installer)
        self.assertIn("xdg/rivendell-complete.desktop", installer)
        self.assertNotIn("rm -rf", installer)
        self.assertNotIn("git reset", installer)
        self.assertNotIn("systemctl enable", installer)

    def test_selected_nas_subfolder_mapping_is_persistent_and_not_secret(self):
        from PyQt5.QtWidgets import QApplication
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        import rdcomplete_control as control
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(control, "CONFIG", pathlib.Path(folder) / "config"), \
                 patch.object(control.Console, "readiness", lambda self: None):
                gui = control.Console()
                gui._save_source_folder("archive", "Music/Old Hits")
                self.assertEqual(gui._load_source_folders()["archive"], "Music/Old Hits")
                p = pathlib.Path(folder) / "config" / "nas-source-folders.json"
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("password", p.read_text().lower())
                with self.assertRaises(ValueError):
                    gui._save_source_folder("archive", "../etc")
                gui.close()

    def test_smb_browser_normalizes_underscores_and_trailing_slash(self):
        from PyQt5.QtWidgets import QApplication
        sys.path.insert(0, str(ROOT / "tools"))
        import rdcomplete_control as control
        self.assertEqual(
            control.normalize_smb_unc("//192.168.0.146/RADIO_BROADCASTING/"),
            ("//192.168.0.146/RADIO_BROADCASTING", "RADIO_BROADCASTING"))
        self.assertEqual(
            control.normalize_nas_folder("Music/Gold_Hits/"),
            "Music/Gold_Hits")
        self.assertEqual(
            control.nas_child_folder("Music", "Rock_Classic"),
            "Music/Rock_Classic")
        for invalid in ("//192.168.0.146/RADIO_BROADCASTING/Evil",
                        "//192.168.0.146/../Evil"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                control.normalize_smb_unc(invalid)
        with self.assertRaises(ValueError):
            control.normalize_smb_unc("//192.168.0.146/U1000/", "other-nas")
        for invalid in ("../escape", "Music/../escape", "/absolute", "Music//bad"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                control.normalize_nas_folder(invalid)

    def test_recursive_nas_discovery_stays_inside_selected_share(self):
        from PyQt5.QtWidgets import QApplication
        import json
        sys.path.insert(0, str(ROOT / "tools"))
        import rdcomplete_control as control
        app = QApplication.instance() or QApplication([])
        with patch.object(control.Console, "readiness", lambda self: None):
            gui = control.Console()
            with patch.object(gui, "execute") as execute:
                gui.nas_server.setText("192.168.0.146")
                gui.nas_protocol.setCurrentText("SMB")
                gui.nas_username.setText("u1000")
                gui.nas_password.setText("test-secret")
                gui.nas_source.setText("//192.168.0.146/U1000/")
                self.assertTrue(gui._discovery_command("folders"))
                argv = execute.call_args.args[0]
                self.assertEqual(argv[argv.index("--share") + 1], "U1000")
                self.assertEqual(argv[argv.index("--folder") + 1], "")
                self.assertNotIn("test-secret", str(argv))
                gui._show_nas_discovery(json.dumps({
                    "folder": "", "folders": ["RADIO_BROADCASTING", "Music"],
                }).encode())
                gui.nas_discovery.setCurrentCell(0, 0)
                gui.nas_open_selected()
                argv = execute.call_args.args[0]
                self.assertEqual(argv[argv.index("--folder") + 1],
                                 "RADIO_BROADCASTING")
                self.assertEqual(gui.nas_browse_folder.text(), "RADIO_BROADCASTING")
                gui._show_nas_discovery(json.dumps({
                    "folder": "RADIO_BROADCASTING", "folders": ["Gold_Hits"],
                }).encode())
                gui.nas_discovery.setCurrentCell(0, 0)
                gui.nas_open_selected()
                argv = execute.call_args.args[0]
                self.assertEqual(argv[argv.index("--folder") + 1],
                                 "RADIO_BROADCASTING/Gold_Hits")
                gui.nas_go_up()
                self.assertEqual(gui.nas_browse_folder.text(), "RADIO_BROADCASTING")
            gui.close()

    def test_native_airplay_staging_preserves_installed_packages(self):
        source = (ROOT / "tools" / "install-airplay-requests.sh").read_text()
        self.assertIn("strings \"$bin\"", source)
        self.assertIn("readelf -h", source)
        self.assertIn("ldd \"$bin\"", source)
        self.assertIn("rdairplay-requests", source)
        self.assertNotIn("dpkg -i", source)
        self.assertNotIn("apt-get", source)
        self.assertNotIn("rddbmgr", source)
        self.assertNotIn("systemctl restart", source)
        self.assertIn("/usr/bin/rdairplay", source)

    def test_controls_never_auto_start_broadcast(self):
        source = (ROOT / "tools" / "rdcomplete_control.py").read_text()
        self.assertIn("QProcess", source)
        self.assertIn("open_listener", source)
        self.assertIn("SeparateChannels", source)
        self.assertIn("restart-audio", source)
        self.assertIn("self.nas_name", source)
        self.assertIn("self.mount_table", source)
        self.assertIn("self.import_source", source)
        self.assertIn("self.nas_discovery", source)
        self.assertIn("self.import_group", source)
        self.assertIn("self.import_folder", source)
        self.assertIn("rdcomplete-browse", source)
        self.assertIn("rdcomplete-source-folders", source)
        self.assertIn("QScrollArea", source)
        self.assertIn("self.add_page(page)", source)
        self.assertIn("refresh_mounts", source)
        self.assertIn('["--group", group, *selected]', source)
        self.assertIn("QMessageBox.question", source)
        self.assertIn('ROOT_HELPER = "/usr/local/libexec/rivendell-complete/rdcomplete_root.py"', source)
        self.assertIn("self._confirm(", source)
        self.assertIn("method=\"POST\"", source)
        self.assertIn('"/mnt/radio-music"', (ROOT / "tools" / "rdcomplete_root.py").read_text())
        self.assertNotIn("os.system(", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("rm -rf", source)


if __name__ == "__main__":
    unittest.main()
