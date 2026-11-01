"""No-JACK regression tests for audio-route configuration and graph checking."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

file=Path(__file__).resolve().parents[1]/"tools"/"rdjackroute.py"
spec=importlib.util.spec_from_file_location("jackroute_testing",file)
assert spec and spec.loader
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)

class JackRouteTests(unittest.TestCase):
    def test_validation(self):
        m.validate([["rd:outL","glasscoder:inL"],["rd:outR","glasscoder:inR"]])
        for val in ([],[["same","same"]],[["A","\n"]],[["a","b"],["a","b"]]):
            with self.assertRaises(m.RouteError):
                m.validate(val)
    def test_discovery_parses_directions(self):
        output="rd:outL\n\tproperties: output,physical\nglasscoder:inL\n\tproperties: input\n"
        class Run: pass
        r=Run();r.returncode=0;r.stdout=output
        with patch.object(m.shutil,"which",return_value="/usr/bin/jack_lsp"):
            with patch.object(m,"run",return_value=r):
                found=m.ports()
        self.assertIn("output",found["rd:outL"])
        self.assertIn("input",found["glasscoder:inL"])
    def test_refuses_wrong_direction(self):
        with patch.object(m,"ports",return_value={"a":{"input"},"b":{"input"}}):
            self.assertTrue(m.reconcile([["a","b"]],check_only=True))

if __name__=="__main__":
    unittest.main()
