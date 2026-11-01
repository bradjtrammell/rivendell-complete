"""Read-only readiness report status and flags."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

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
    def test_missing_config_is_hard_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            c=module.Check()
            c.evaluate(Path(temp)/"not-here")
            self.assertEqual(c.exit_status(False),1)

if __name__=="__main__":
    unittest.main()
