"""Live-safe RML dispatch and guarded top-hour regression tests."""
from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

base=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(base/"tools"))
spec=importlib.util.spec_from_file_location("rdlive_testing",base/"tools"/"rdlive.py")
assert spec and spec.loader
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)
from rdrequests import Store


class LiveTests(unittest.TestCase):
    def test_protects_each_hard_break(self):
        now=datetime(2026,11,2,12,59,0)
        self.assertFalse(m.eligible_window(now,180000,[12*3600000,13*3600000]))
        now=datetime(2026,11,2,12,0,5)
        self.assertTrue(m.eligible_window(now,180000,[12*3600000,13*3600000]))
        self.assertFalse(m.eligible_window(now,900001,[13*3600000]))
    def test_ledger_binds_to_original_production_log(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as temp:
            now=datetime(2026,11,2,12,10)
            plan=Path(temp)/"2026-11-02.plan.json"
            rows=[{"start_ms":h*3600000,"hard":True,"kind":"top-hour-id"}
                  for h in range(24)]
            plan.write_text(json.dumps({"log_name":"PROD_NEXT","events":rows}))
            self.assertEqual(len(m.load_ledger(plan,now)),24)
            plan.write_text(json.dumps({"log_name":"invalid log","events":rows}))
            with self.assertRaises(m.LiveError):
                m.load_ledger(plan,now)

    def test_validates_current_date_and_24_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            day=datetime(2026,11,2,12,0,0)
            ledger=Path(temp)/"2026-11-02.plan.json"
            data=[{"start_ms":h*3600000,"hard":True,"kind":"top-hour-id"} for h in range(24)]
            ledger.write_text(json.dumps(data))
            self.assertEqual(len(m.load_ledger(ledger,day)),24)
            with self.assertRaises(m.LiveError):
                m.load_ledger(ledger,datetime(2026,11,3,12,0))
    def test_claim_once_and_no_duplicate_dispatch(self):
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/"req.sqlite")
            request=store.submit(100001,"A","f"*64,{100001},now=1000)
            with store.connect() as conn:
                self.assertTrue(m.claim(conn,request["id"],100001,1001))
                self.assertFalse(m.claim(conn,request["id"],100001,1001))
                m.status(conn,request["id"],"delivery_unknown")
                self.assertEqual(conn.execute(
                    "SELECT status FROM live_dispatches WHERE request_id=?",
                    (request["id"],)).fetchone()[0],"delivery_unknown")
    def test_rml_ack_positive_and_negative(self):
        # Do not bind the live station's fixed RML UDP port. On a running
        # workstation ripcd already owns 5858/5860. Use isolated ephemeral
        # loopback ports for this deterministic protocol unit test.
        for sign in ("+", "-"):
            with self.subTest(sign=sign):
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as echo:
                    echo.bind(("127.0.0.1", 0))
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reply_probe:
                        reply_probe.bind(("127.0.0.1", 0))
                        reply_port = reply_probe.getsockname()[1]
                    echo_port = echo.getsockname()[1]
                    errors = []

                    def responder():
                        try:
                            echo.settimeout(3)
                            payload, peer = echo.recvfrom(512)
                            if payload != b"PX 1 123456 0 SEGUE!":
                                raise AssertionError(f"Unexpected RML payload: {payload!r}")
                            echo.sendto(
                                b"PX 1 123456 0 SEGUE " + sign.encode() + b"!",
                                ("127.0.0.1", reply_port)
                            )
                        except Exception as exc:
                            errors.append(exc)

                    with patch.object(m, "ECHO_PORT", echo_port), patch.object(m, "REPLY_PORT", reply_port):
                        thread = threading.Thread(target=responder)
                        thread.start()
                        try:
                            self.assertEqual(m.send_px(123456, timeout=2), sign == "+")
                        finally:
                            thread.join(timeout=4)
                        self.assertFalse(thread.is_alive(), "RML test responder hung")
                        self.assertFalse(errors, f"RML responder failed: {errors!r}")

    def test_explicit_nack_is_not_timeout(self):
        with self.assertRaises(m.LiveError):
            m.send_px(0)


if __name__=="__main__":
    unittest.main()
