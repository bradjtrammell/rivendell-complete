"""Conservative repair of existing imported NAS carts, without re-importing music."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import rdcomplete_audio_audit as audit


def good_row():
    return {
        "number": 100001, "type": 1, "group": "MUSIC", "quantity": 1,
        "cart_validity": 2, "cut_name": "100001_001", "cut_cart": 100001,
        "length": 188000, "cut_validity": 2,
        "sun": "Y", "mon": "Y", "tue": "Y", "wed": "Y",
        "thu": "Y", "fri": "Y", "sat": "Y",
    }


class AuditTests(unittest.TestCase):
    def test_valid_imported_cuts_are_left_untouched(self):
        self.assertEqual(audit.classify(100001, good_row()), [])

    def test_missing_cut_and_cart_do_not_authorize_deletion(self):
        row = good_row()
        row["cut_name"] = None
        row["cut_cart"] = None
        self.assertEqual(audit.classify(100001, row), ["cut_missing"])
        self.assertEqual(audit.classify(100001, None), ["cart_missing"])
        row = good_row()
        row["type"] = 2
        self.assertEqual(audit.classify(100001, row), ["cart_not_audio"])

    def test_bad_metadata_is_identified_precisely(self):
        row = good_row()
        row["length"] = 0
        row["quantity"] = 0
        row["cart_validity"] = 0
        row["cut_validity"] = 0
        for day in ("sun", "mon", "tue", "wed", "thu", "fri", "sat"):
            row[day] = "N"
        self.assertEqual(set(audit.classify(100001, row)), {
            "zero_length_cut", "incorrect_cut_quantity",
            "invalid_cart_flag", "invalid_cut_flag", "no_enabled_days"
        })

    def test_snapshot_is_private_and_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "snapshot"
            target = audit.create_recovery_copy([{"cart": 100001}], folder)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads(target.read_text()), [{"cart": 100001}])
            # A second audit does not rewrite the original recovery snapshot.
            another = audit.create_recovery_copy([{"cart": 100002}], folder)
            self.assertNotEqual(target, another)
            self.assertEqual(json.loads(target.read_text()), [{"cart": 100001}])
            # No backend deletion, no original media mutation.
            self.assertTrue(target.is_file())

    def test_untrusted_snapshot_folder_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "actual").mkdir()
            (root / "alias").symlink_to(root / "actual")
            with self.assertRaises(audit.AuditError):
                audit.create_recovery_copy([{"cart": 100001}], root / "alias")


if __name__ == "__main__":
    unittest.main()
