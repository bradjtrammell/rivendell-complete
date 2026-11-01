"""Sweeper overlays only on proven, sufficiently long instrumental intros."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import unittest
f=Path(__file__).resolve().parents[1]/"tools"/"rdsweepers.py"
spec=importlib.util.spec_from_file_location("sweeper_tests",f)
assert spec and spec.loader
s=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=s
spec.loader.exec_module(s)

class SweeperTests(unittest.TestCase):
    def test_reject_unknown_or_short_intros(self):
        intros={100001:8000,100002:2500}
        sweepers=[(900001,6000),(900002,4000)]
        self.assertIsNone(s.pick_sweeper(100999,4,4,intros,sweepers))
        self.assertIsNone(s.pick_sweeper(100002,4,4,intros,sweepers))
        self.assertIsNone(s.pick_sweeper(100001,3,4,intros,sweepers))
        self.assertEqual(s.pick_sweeper(100001,4,4,intros,sweepers),900001)
    def test_validation_does_not_allow_invalid_duration(self):
        with self.assertRaises(s.SweeperError):
            s.validate_catalog({"vocal_intros_ms":{"100001":9000},
                                "sweepers":[{"cart":123456,"duration_ms":-2}]})
    def test_only_reserved_panel_receives_commands(self):
        commands=s.rml_commands(900001)
        self.assertEqual(commands,(b"PE S50 1 1 900001!",b"PP S50 1 1!"))
        with self.assertRaises(s.SweeperError):
            s.rml_commands(0)
    def test_selection_is_deterministic(self):
        intro={100001:10000}
        sw=[(900001,4000),(900002,5000)]
        self.assertEqual(s.pick_sweeper(100001,4,4,intro,sw),900001)
        self.assertEqual(s.pick_sweeper(100001,8,4,intro,sw),900002)

if __name__=="__main__":
    unittest.main()
