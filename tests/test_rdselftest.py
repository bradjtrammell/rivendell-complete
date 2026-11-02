"""Read-only readiness report status and flags."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import subprocess

f=Path(__file__).resolve().parents[1]/"tools"/"rdselftest.py"
spec=importlib.util.spec_from_file_location("rdselftest_tested",f)
assert spec and spec.loader
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)

class DiagnosticTests(unittest.TestCase):
    def test_status_codes(self):
        c=module.Check()
        self.assertEqual(c.exit_status(True),0)
        c.add("test",False,"offline",critical=False)
        self.assertEqual(c.exit_status(False),0)
        self.assertEqual(c.exit_status(True),2)
        c.add("critical",False,"invalid",critical=True)
        self.assertEqual(c.exit_status(True),1)
    def test_local_filesystem_is_not_a_nas_mount(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"music"
            root.mkdir()
            (root/"track.mp3").write_bytes(b"test")
            config=Path(temp)/"rd.conf"
            config.write_text("[ExternalAudio]\nRoot="+str(root)+"\n")
            c=module.Check()
            def fake_command(program,arguments,timeout=8):
                if program=="findmnt":
                    return subprocess.CompletedProcess([],0,"/dev/sda1 ext4 rw,relatime\n","")
                return None
            with mock.patch.object(c,"command",side_effect=fake_command):
                c.evaluate(config)
            results={x["name"]:x for x in c.results}
            self.assertEqual(results["nas-mounted"]["status"],"fail")

    def test_missing_config_is_hard_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            c=module.Check()
            c.evaluate(Path(temp)/"not-here")
            self.assertEqual(c.exit_status(False),1)

if __name__=="__main__":
    unittest.main()
