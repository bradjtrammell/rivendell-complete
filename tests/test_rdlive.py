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
        # Simulate the documented Rivendell UDP ports entirely on loopback.
        for sign in ("+","-"):
            with self.subTest(sign=sign):
                ready=threading.Event()
                def responder():
                    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
                        s.bind(("127.0.0.1",m.ECHO_PORT))
                        s.settimeout(3)
                        ready.set()
                        payload,peer=s.recvfrom(512)
                        self.assertEqual(payload,b"PX 1 123456 0 SEGUE!")
                        s.sendto(b"PX 1 123456 0 SEGUE "+sign.encode()+b"!",
                                 ("127.0.0.1",m.REPLY_PORT))
                thread=threading.Thread(target=responder)
                thread.start()
                self.assertTrue(ready.wait(2))
                self.assertEqual(m.send_px(123456,timeout=1),sign=="+")
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
    def test_explicit_nack_is_not_timeout(self):
        with self.assertRaises(m.LiveError):
            m.send_px(0)


if __name__=="__main__":
    unittest.main()
