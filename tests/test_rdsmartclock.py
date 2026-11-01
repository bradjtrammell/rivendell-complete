"""Synthetic 24-hour smart clock generation: no NAS, DB or audio required."""
from __future__ import annotations
from datetime import date
import importlib.util
from pathlib import Path
import sys
import unittest

file=Path(__file__).resolve().parents[1]/"tools"/"rdsmartclock.py"
spec=importlib.util.spec_from_file_location("rdsmartclock_tested",file)
assert spec and spec.loader
smart=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=smart
spec.loader.exec_module(smart)


class SmartClockTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(service="MUSIC",top_hour_cart=999999,
                           rotation=["POWER"],artist_separation_minutes=60,
                           album_separation_minutes=60,
                           title_separation_minutes=1440,
                           safety_margin_ms=0,max_hour_gap_ms=0)
        self.catalog=[
            smart.Track(cart=i+100000,group="POWER",title=f"Song {i}",
                        artist=f"Artist {i}",album=f"Album {i}",
                        length_ms=3590000)
            for i in range(30)
        ]
    def test_exact_top_hour_sequence_and_separation(self):
        events=smart.plan_day(self.catalog,self.config,date(2026,11,2),10000)
        self.assertEqual(len(events),48)
        ids=[e for e in events if e.hard]
        self.assertEqual(len(ids),24)
        self.assertEqual([e.start_ms for e in ids],
                         [x*3600000 for x in range(24)])
        self.assertEqual(len(set(e.cart for e in events if not e.hard)),24)
        self.assertEqual(events[-1].start_ms+events[-1].length_ms,86400000)
        commands=smart.commands(events,"MUSIC",date(2026,11,2),"MUSIC20261102")
        self.assertTrue(commands.startswith("new MUSIC20261102\nsetservice MUSIC\n"))
        self.assertEqual(commands.count("settime "),24)
        self.assertIn("settime 0 hard 00:00:00",commands)
        self.assertIn("settime 46 hard 23:00:00",commands)
        self.assertTrue(commands.endswith("save\nbye\n"))
    def test_no_unsafe_filename_or_command_injection(self):
        with self.assertRaises(smart.PlanError):
            smart.settings(dict(self.config,service="-bad"))
        with self.assertRaises(smart.PlanError):
            smart.settings(dict(self.config,rotation=["POWER;rm"]))
        with self.assertRaises(smart.PlanError):
            smart.commands([],"MUSIC",date(2026,11,2),"a new log")
    def test_failed_hour_refuses_to_air(self):
        catalog=[smart.Track(cart=i+1,group="POWER",title=f"Song {i}",
               artist=f"Artist {i}",album=f"Album {i}",length_ms=170000)
               for i in range(25)]
        with self.assertRaises(smart.PlanError):
            smart.plan_day(catalog,self.config,date(2026,11,2),10000)
    def test_deterministic_for_given_day(self):
        a=smart.plan_day(self.catalog,self.config,date(2026,11,2),10000)
        b=smart.plan_day(self.catalog,self.config,date(2026,11,2),10000)
        self.assertEqual(a,b)


if __name__=="__main__":
    unittest.main()
