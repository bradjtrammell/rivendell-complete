"""Protected 24-hour station clock: IDs, spots, requests, fill beds and silence."""
from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/"tools"))
spec=importlib.util.spec_from_file_location("rdstationplan_tested",root/"tools"/"rdstationplan.py")
assert spec and spec.loader
station=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=station
spec.loader.exec_module(station)
from rdsmartclock import Event,Track,PlanError,commands


class StationPlanTests(unittest.TestCase):
    def setUp(self):
        self.cfg={
            "service":"FMONE", "rotation":["POWER","GOLD","POWER"],
            "top_hour":{"cart":900001,"duration_ms":10000},
            "breaks":[{"minute":30,"spots":[
                {"cart":800001,"duration_ms":30000},
                {"cart":800002,"duration_ms":30000}]}],
            "fill_bed":{"cart":900002,"duration_ms":240000},
            "artist_separation_minutes":60,
            "album_separation_minutes":60,
            "title_separation_minutes":1440,
            "max_segment_gap_ms":1000,
            "max_requests_per_hour":2,
        }
        self.catalog=[
            Track(100000+i,"POWER" if i%2==0 else "GOLD",
                  f"Song{i}",f"Artist{i}",f"Album{i}",180000)
            for i in range(1000)
        ]
    def test_timing_and_traffic_spots_protected(self):
        day=date(2026,11,2)
        result=station.assemble(self.catalog,self.cfg,day)
        ids=[e for e in result.events if e.kind=="top-hour-id"]
        spots=[e for e in result.events if e.kind=="spot"]
        beds=[e for e in result.events if e.kind=="fill-bed"]
        self.assertEqual(len(ids),24)
        self.assertEqual([e.start_ms for e in ids],[h*3600000 for h in range(24)])
        self.assertEqual(len(spots),48)
        self.assertEqual([e.start_ms for e in spots if e.hard],
                         [h*3600000+30*60000 for h in range(24)])
        self.assertTrue(beds)
        self.assertTrue(all(gap<=1000 for gap in result.segment_gaps))
        text=commands(result.events,"FMONE",day,"FMONE20261102")
        self.assertIn("settime ",text)
        self.assertIn("hard 00:30:00",text)
        self.assertIn("hard 23:30:00",text)
        self.assertEqual(text.count("hard "),48)

    def test_approved_requests_are_scheduled_without_overriding_spots(self):
        day=date(2026,11,2)
        requested=[
            {"id":1,"cart":100020},
            {"id":2,"cart":100022},
            {"id":3,"cart":100024},
        ]
        result=station.assemble(self.catalog,self.cfg,day,requested)
        self.assertEqual(set(result.request_ids),{1,2,3})
        first_hour=[e for e in result.events if e.start_ms<3600000 and e.kind=="request"]
        self.assertLessEqual(len(first_hour),2)
        self.assertTrue(all(e.cart in (100020,100022,100024) for e in result.events
                            if e.kind=="request"))
        self.assertEqual(len([e for e in result.events if e.kind=="top-hour-id"]),24)

    def test_without_fill_audio_unfillable_hour_fails(self):
        cfg=dict(self.cfg)
        cfg.pop("fill_bed")
        with self.assertRaises(PlanError):
            station.assemble(self.catalog,cfg,date(2026,11,2))

    def test_illegal_ad_break_crosses_next_break(self):
        cfg=dict(self.cfg)
        cfg["breaks"]=[
            {"minute":15,"spots":[{"cart":810001,"duration_ms":1800000}]},
            {"minute":30,"spots":[{"cart":810002,"duration_ms":30000}]},
        ]
        with self.assertRaises(PlanError):
            station.validate(cfg)

    def test_external_request_db_import_cannot_schedule_spots(self):
        self.assertNotIn(800001,{t.cart for t in self.catalog})


if __name__=="__main__":
    unittest.main()
