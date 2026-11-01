"""No-network log generator safety tests."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
path=Path(__file__).resolve().parents[1]/"tools"/"rdloggen.py"
spec=importlib.util.spec_from_file_location("rdloggen_test",path)
assert spec and spec.loader
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)
class LogTests(unittest.TestCase):
    def test_protected_generate_arguments(self):
        self.assertEqual(mod.command("FMONE",0),["rdlogmanager","-P","-g","-s","FMONE","-d","0"])
    def test_name_and_offset_validation(self):
        for value in ("", "A B", "X"*11, "-h", "A;rm"):
            with self.assertRaises(mod.LogError): mod.command(value,0)
        for val in (-1,31):
            with self.assertRaises(mod.LogError): mod.command("FMONE",val)
    def test_dry_run_never_starts_rivendell(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(mod.generate("FMONE",7,True,Path(root)/"lock"),0)
if __name__=="__main__":
    unittest.main()
