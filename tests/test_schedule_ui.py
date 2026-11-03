"""Native schedule page validation, exact categories, measured timing and safe staging."""
from __future__ import annotations

from pathlib import Path
import os
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from rdcomplete_schedule_ui import (
    ScheduleError, SchedulePanel, derive_config, secure_write, validate_spec
)


class SchedulingTests(unittest.TestCase):
    def make_spec(self):
        from PyQt5.QtCore import QDate
        return validate_spec("MUSIC,GOLD,MUSIC", 900001, 900101, 0, 4,
                             QDate.currentDate().addDays(1).toString("yyyy-MM-dd"),
                             "PROD_NEXT")

    def test_valid_rotation_keeps_weighting(self):
        spec = self.make_spec()
        self.assertEqual(spec["rotation"], ["MUSIC", "GOLD", "MUSIC"])
        self.assertEqual(spec["id"], 900001)
        self.assertEqual(spec["jingle"], 900101)

    def test_invalid_categories_or_missing_id_fail_closed(self):
        spec = self.make_spec()
        for groups, station_id, name in [
            ("", 900001, "FUTURE"),
            ("MUSIC,/tmp", 900001, "FUTURE"),
            ("MUSIC", 0, "FUTURE"),
            ("MUSIC", 900001, "../../unsafe"),
        ]:
            with self.subTest(groups=groups, station_id=station_id, name=name):
                with self.assertRaises(ScheduleError):
                    validate_spec(groups, station_id, 0, 0, 4,
                                  spec["date"], name)

    def test_measured_ids_jingles_and_fill_bed_are_not_guessed(self):
        spec = self.make_spec()
        rows = {"tracks": [
                    {"cart": 100001, "group": "MUSIC", "length_ms": 192000},
                    {"cart": 100002, "group": "GOLD", "length_ms": 182000},
                ],
                "specials": {
                    "top_hour": {"cart": 900001, "duration_ms": 12000},
                    "jingle": {"cart": 900101, "duration_ms": 1800},
                }}
        tracks, config = derive_config(spec, rows)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(config["top_hour"]["duration_ms"], 12000)
        self.assertEqual(config["jingle"]["duration_ms"], 1800)
        self.assertEqual(config["jingle_every"], 4)
        self.assertNotIn("fill_bed", config)
        rows["specials"].pop("jingle")
        with self.assertRaises(ScheduleError):
            derive_config(spec, rows)

    def test_write_never_follows_symlink_or_weak_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "schedule"
            path = secure_write("working-schedule-config.json",
                                {"rotation": ["MUSIC"]}, state=state)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(state.stat().st_mode & 0o777, 0o700)
            self.assertIn("MUSIC", path.read_text())
            path.unlink()
            path.symlink_to(root / "missing")
            with self.assertRaises(ScheduleError):
                secure_write("working-schedule-config.json", {}, state=state)
            path.unlink()
            state.chmod(0o755)
            with self.assertRaises(ScheduleError):
                secure_write("working-schedule-config.json", {}, state=state)

    def test_page_renders_with_future_date_and_confirm_disabled(self):
        from PyQt5.QtWidgets import QApplication, QWidget
        app = QApplication.instance() or QApplication([])
        parent = QWidget()
        panel = SchedulePanel(parent)
        self.assertEqual(panel.id_cart.value(), 0)
        self.assertFalse(panel.commit_button.isEnabled())
        self.assertEqual(panel.groups.text(), "MUSIC")
        panel.close()
        parent.close()


if __name__ == "__main__":
    unittest.main()
