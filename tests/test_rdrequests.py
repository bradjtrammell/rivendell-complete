"""Authenticated request API and durable queue regression tests."""
from __future__ import annotations

import hashlib
import http.client
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

file=Path(__file__).resolve().parents[1]/"tools"/"rdrequests.py"
spec=importlib.util.spec_from_file_location("rdrequests_testing",file)
assert spec and spec.loader
mod=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=mod.Store(self.root/"queue.sqlite")
        self.client="b"*64
    def test_queue_approval_and_repeat_protection(self):
        first=self.store.submit(100001,"Listener",self.client,{100001},False,now=20000)
        self.assertEqual(first["status"],"pending")
        self.assertFalse(self.store.approve(99999,"approved"))
        self.assertTrue(self.store.approve(first["id"],"approved"))
        self.assertFalse(self.store.approve(first["id"],"approved"))
        with self.assertRaises(mod.RequestError):
            self.store.submit(100001,"Second listener","c"*64,{100001},True,now=20100)
        self.assertEqual(self.store.scheduled([first["id"]],"STATION1102",when=20200),1)
        self.assertEqual(self.store.queue("scheduled")[0]["scheduled_log"],"STATION1102")
    def test_rate_limit_and_category_restriction(self):
        with self.assertRaises(mod.RequestError):
            self.store.submit(900001,"Caller",self.client,{100001},now=100)
        for i in range(4):
            self.store.submit(100001+i,"Caller",self.client,set(range(100001,100005)),
                              now=1000+i)
        with self.assertRaises(mod.RequestError):
            self.store.submit(100005,"Caller",self.client,{100005},now=1030)
    def test_atomic_schedule_on_conflict(self):
        a=self.store.submit(100001,"Caller",self.client,{100001},now=100)
        b=self.store.submit(100002,"Caller",self.client,{100002},now=100)
        with self.assertRaises(mod.RequestError):
            self.store.scheduled([a["id"],999999,b["id"]],"STATION1102")
        self.assertEqual(len(self.store.queue("approved")),2)
    def test_http_token_validation_and_submission(self):
        catalog=self.root/"catalog.json"
        catalog.write_text(json.dumps([{"cart":100001,"group":"POWER"},{"cart":900001,"group":"ID"}]))
        server=mod.RequestServer(("127.0.0.1",0),self.store,
                                "L"*48,"A"*48,catalog,frozenset(("POWER",)),True)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def call(method,path,body=None,token=None):
            conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            headers={"Content-Type":"application/json"}
            if token: headers["Authorization"]="Bearer "+token
            payload=json.dumps(body) if body is not None else None
            conn.request(method,path,body=payload,headers=headers)
            resp=conn.getresponse()
            data=json.loads(resp.read())
            status=resp.status
            conn.close()
            return status,data
        self.assertEqual(call("POST","/api/v1/requests",{"cart":100001,"requester":"Caller"})[0],401)
        self.assertEqual(call("POST","/api/v1/requests",{"cart":900001,"requester":"Caller"},"L"*48)[0],400)
        status,payload=call("POST","/api/v1/requests",{"cart":100001,"requester":"Caller"},"L"*48)
        self.assertEqual(status,202)
        self.assertEqual(payload["status"],"approved")
        self.assertEqual(call("GET","/api/v1/requests",token="A"*48)[0],200)
        self.assertEqual(call("GET","/healthz")[0],200)
    def test_public_listener_page_requires_csrf_and_moderation(self):
        catalog=self.root/"catalog-public.json"
        catalog.write_text(json.dumps([{
            "cart":100001,"group":"MUSIC",
            "title":"Example Track","artist":"Example Artist",
        }]))
        server=mod.RequestServer(("127.0.0.1",0),self.store,
                                "L"*48,"A"*48,catalog,frozenset(("MUSIC",)),
                                False,public_portal=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def call(method,path,payload=None):
            conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            data=json.dumps(payload) if payload is not None else None
            conn.request(method,path,body=data,headers={"Content-Type":"application/json"})
            response=conn.getresponse()
            body=response.read()
            status=response.status
            conn.close()
            return status,body
        code,page=call("GET","/requests")
        self.assertEqual(code,200)
        self.assertIn(b"What should we play next?",page)
        self.assertNotIn(("L"*48).encode(),page)
        code,asset=call("GET","/requests/app.js")
        self.assertEqual(code,200)
        self.assertIn(b"/api/v1/public/requests",asset)
        code,catalog_data=call("GET","/api/v1/public/catalog")
        self.assertEqual(code,200)
        public=json.loads(catalog_data)
        self.assertEqual(public["songs"][0]["title"],"Example Track")
        self.assertNotIn("token",str(public).lower())
        payload={"cart":100001,"requester":"Listener","csrf":"invalid"}
        self.assertEqual(call("POST","/api/v1/public/requests",payload)[0],403)
        payload["csrf"]=public["csrf"]
        code,response=call("POST","/api/v1/public/requests",payload)
        self.assertEqual(code,202)
        self.assertEqual(json.loads(response)["status"],"pending")
        self.assertEqual(len(self.store.queue("pending")),1)

    def test_client_hmac_does_not_expose_ip(self):
        digest=mod.identity_hash("127.0.0.1","secret")
        self.assertEqual(len(digest),64)
        self.assertNotIn("127.0.0.1",digest)


if __name__=="__main__":
    unittest.main()
