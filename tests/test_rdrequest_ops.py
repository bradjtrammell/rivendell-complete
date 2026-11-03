"""RDAirPlay request queue bridge: approval, protected timing, and deduplication."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import rdrequest_ops as bridge
from rdrequests import Store


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "requests.sqlite")
        self.client = "a" * 64
        self.now = datetime(2026, 11, 2, 12, 10)
        self.plan = self.root / "plans"
        self.plan.mkdir()
        self.ledger = self.plan / "2026-11-02.plan.json"
        self.ledger.write_text(json.dumps({
            "log_name": "PROD_NEXT",
            "events": [
                {"start_ms": h * 3600000, "hard": True,
                 "kind": "top-hour-id"} for h in range(24)]
        }))
        self.catalog = {100001: {"cart": 100001, "group": "MUSIC",
                                 "title": "Track", "artist": "Performer",
                                 "length_ms": 180000}}

    def test_requester_visible_in_operator_queue(self):
        request = self.store.submit(100001, "Listener One", self.client,
                                    {100001}, False, now=100)
        rows = bridge.list_requests(self.store, self.catalog)
        self.assertEqual(rows["pending"], 1)
        self.assertEqual(rows["requests"][0]["requester"], "Listener One")
        self.assertEqual(rows["requests"][0]["title"], "Track")
        self.assertTrue(self.store.approve(request["id"], "approved"))
        rows = bridge.list_requests(self.store, self.catalog)
        self.assertEqual(rows["approved"], 1)

    def test_protected_future_id_and_manual_reservation_deduplicate(self):
        request = self.store.submit(100001, "Listener", self.client,
                                    {100001}, True, now=100)
        original = bridge.datetime
        class Clock:
            @staticmethod
            def now():
                class Fake:
                    def astimezone(self):
                        return self_value
                self_value = datetime(2026, 11, 2, 12, 10).astimezone()
                return Fake()
        bridge.datetime = Clock
        try:
            result = bridge.reserve(self.store, request["id"], self.catalog,
                                  loaded_log="PROD_NEXT", plan_dir=self.plan)
            self.assertEqual(result["status"], "reserved")
            with self.assertRaises(bridge.ConsoleError):
                bridge.reserve(self.store, request["id"], self.catalog,
                                  loaded_log="PROD_NEXT", plan_dir=self.plan)
            queued = bridge.complete(self.store, request["id"], 100001, True)
            self.assertEqual(queued["status"], "queued")
            self.assertEqual(self.store.queue("approved"), [])
            self.assertEqual(self.store.queue("scheduled")[0]["id"], request["id"])
            with self.assertRaises(bridge.ConsoleError):
                bridge.complete(self.store, request["id"], 100001, True)
        finally:
            bridge.datetime = original

    def test_near_legal_id_rejected_even_for_manual_request(self):
        request = self.store.submit(100001, "Listener", self.client,
                                    {100001}, True, now=100)
        original = bridge.datetime
        class Clock:
            @staticmethod
            def now():
                class Fake:
                    def astimezone(self):
                        return datetime(2026, 11, 2, 12, 58).astimezone()
                return Fake()
        bridge.datetime = Clock
        try:
            with self.assertRaises(bridge.ConsoleError):
                bridge.reserve(self.store, request["id"], self.catalog, loaded_log="PROD_NEXT", plan_dir=self.plan)
            self.assertEqual(len(self.store.queue("approved")), 1)
        finally:
            bridge.datetime = original

    def test_uncertain_queue_outcome_is_not_retried(self):
        request = self.store.submit(100001, "Listener", self.client,
                                    {100001}, True, now=100)
        original = bridge.datetime
        class Clock:
            @staticmethod
            def now():
                class Fake:
                    def astimezone(self):
                        return datetime(2026, 11, 2, 12, 10).astimezone()
                return Fake()
        bridge.datetime = Clock
        try:
            bridge.reserve(self.store, request["id"], self.catalog, loaded_log="PROD_NEXT", plan_dir=self.plan)
            pending = bridge.complete(self.store, request["id"], 100001, False)
            self.assertEqual(pending["status"], "delivery_unknown")
            with self.assertRaises(bridge.ConsoleError):
                bridge.reserve(self.store, request["id"], self.catalog, loaded_log="PROD_NEXT", plan_dir=self.plan)
        finally:
            bridge.datetime = original

    def test_manual_request_requires_active_operator_and_not_daily_ledger(self):
        request = self.store.submit(100001, "Listener", self.client,
                                    {100001}, True, now=100)
        with self.assertRaises(bridge.LiveError):
            bridge.reserve(self.store, request["id"], self.catalog,
                           loaded_log="", plan_dir=self.root / "missing")
        result = bridge.reserve(self.store, request["id"], self.catalog,
                                loaded_log="", plan_dir=self.root / "missing",
                                manual=True)
        self.assertEqual(result["status"], "reserved")
        with self.assertRaises(bridge.ConsoleError):
            bridge.reserve(self.store, request["id"], self.catalog,
                           manual=True, plan_dir=self.root / "missing")

    def test_file_permissions_before_on_air_bridge(self):
        path = self.root / "catalog.json"
        path.write_text(json.dumps(list(self.catalog.values())))
        path.chmod(0o600)
        bridge.owned_regular(path, 1024)
        path.chmod(0o644)
        with self.assertRaises(bridge.ConsoleError):
            bridge.owned_regular(path, 1024)


if __name__ == "__main__":
    unittest.main()
