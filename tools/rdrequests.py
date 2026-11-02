#!/usr/bin/env python3
"""Authenticated listener-request queue for one Rivendell Complete station.

No direct log mutation: requests are recorded for safe insertion by the clock
planner, avoiding interruptions to legal IDs and paid traffic.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import threading
import time
from urllib.parse import urlsplit

MAX_BODY = 8192
MAX_REQUESTS_PER_HOUR = 4
MIN_REPEAT_SECONDS = 3 * 3600



# Public-facing listener experience. These assets have no embedded credentials.
# They are served only by the explicitly enabled loopback-bound portal.
PUBLIC_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>Request a song · Production Radio</title>
<link rel="stylesheet" href="/requests/style.css"></head>
<body><div class="site"><header><div class="mast">PRODUCTION <span>RADIO</span></div>
<p>YOUR MUSIC, YOUR REQUEST</p></header>
<main><section class="intro"><h1>What should we play next?</h1>
<p>Search the station library and submit a request. A producer reviews each request before scheduling it.</p>
</section><section class="search"><label for="search">Find a song or artist</label>
<input id="search" type="search" autocomplete="off" placeholder="Type to search the music library" maxlength="120">
<p class="feedback" id="feedback" role="status" aria-live="polite">Loading available music…</p>
<ul id="songs" aria-label="Available songs"></ul></section>
<section class="request" id="form-panel" hidden><h2 id="selected-title">Selected song</h2>
<form id="request-form"><label for="name">Your name</label>
<input id="name" name="name" minlength="1" maxlength="64" required autocomplete="name">
<button type="submit" id="send">Send song request</button></form>
<p class="feedback" role="status" aria-live="polite" id="result"></p></section></main>
<footer>Requests are reviewed and are not guaranteed to air. No account required.</footer></div>
<script src="/requests/app.js" defer></script></body></html>"""
PUBLIC_CSS = """*{box-sizing:border-box}body{margin:0;background:#f7f3e8;color:#262721;font:16px/1.55 system-ui,Arial,sans-serif}
.site{max-width:1030px;margin:auto;padding:0 22px}header{background:#252c26;color:white;margin:0 -22px;padding:24px 22px 17px;
display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap}
.mast{font-weight:900;font-size:27px;letter-spacing:-1px}.mast span{color:#ffb97d}
header p{font-size:12px;letter-spacing:.1em;color:#f4d8b9}main{display:grid;grid-template-columns:3fr 2fr;gap:36px;padding:52px 0 24px}
.intro{grid-column:1 / -1}.intro h1{font-size:clamp(32px,5vw,58px);line-height:1.1;letter-spacing:-.045em;margin:0}
.intro p{max-width:680px;color:#50584c;margin:20px 0 0}.search,.request{min-width:0}
label{display:block;font-weight:700;margin:0 0 9px}input{width:100%;min-height:48px;padding:12px;border:2px solid #747a6d;
background:#fff;font:inherit}input:focus,button:focus-visible{outline:3px solid #c24f2d;outline-offset:2px}
ul{padding:0;list-style:none;max-height:460px;overflow-y:auto}li{border-bottom:1px solid #ced4c7}
li button{width:100%;text-align:left;background:none;border:0;color:#25352a;padding:14px 7px;font:inherit;cursor:pointer}
li button:hover{background:#e0e8d9}.song{font-weight:750;display:block}.artist{color:#566255;font-size:14px}
button[type=submit]{background:#b94d2f;border:0;color:white;font:700 16px system-ui;padding:14px 22px;cursor:pointer;margin-top:18px}
.request{border-top:5px solid #b94d2f;background:#fffdfa;padding:24px;align-self:start}
.request h2{font-size:22px;line-height:1.25;margin-top:0}.feedback{color:#4c5b50;font-size:14px}
footer{border-top:1px solid #cad0c4;color:#535e53;padding:20px 0 34px;font-size:13px}
@media(max-width:700px){main{display:block;padding-top:36px}.request{margin-top:24px}header{display:block}.intro h1{font-size:36px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}"""
PUBLIC_JS = """'use strict';
const qs=(id)=>document.getElementById(id),songs=qs('songs'),feedback=qs('feedback');
const form=qs('request-form'),panel=qs('form-panel'),result=qs('result');
let list=[],csrf='',chosen=null;
const text=(el,v)=>{el.textContent=String(v??'')};
function render(){
  songs.replaceChildren();const q=qs('search').value.trim().toLocaleLowerCase();
  const matching=list.filter(x=>(x.title+' '+x.artist).toLocaleLowerCase().includes(q)).slice(0,80);
  text(feedback,matching.length?matching.length+' matching songs shown':'No matching songs');
  for(const track of matching){
    const li=document.createElement('li'),btn=document.createElement('button');
    btn.type='button';btn.setAttribute('aria-label','Request '+track.title+' by '+track.artist);
    const a=document.createElement('span'),b=document.createElement('span');
    a.className='song';b.className='artist';text(a,track.title);text(b,track.artist);
    btn.append(a,b);btn.addEventListener('click',()=>{
      chosen=track;panel.hidden=false;text(qs('selected-title'),track.title+' — '+track.artist);
      text(result,'');qs('name').focus();
    });
    li.append(btn);songs.append(li);
  }
}
async function load(){
  try{
    const response=await fetch('/api/v1/public/catalog',{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw Error('Station library is unavailable');
    const obj=await response.json();list=obj.songs;csrf=obj.csrf;
    if(!Array.isArray(list)||!csrf)throw Error('Station catalog is not ready');render();
  }catch(e){text(feedback,e.message);songs.replaceChildren()}
}
qs('search').addEventListener('input',render);
form.addEventListener('submit',async(ev)=>{
  ev.preventDefault();if(!chosen)return;const button=qs('send');button.disabled=true;
  try{
    const r=await fetch('/api/v1/public/requests',{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({cart:chosen.cart,requester:qs('name').value.trim(),csrf})});
    const value=await r.json();if(!r.ok)throw Error(value.error||'Request was not accepted');
    text(result,'Request received for review. Thank you!');form.reset();panel.hidden=true;
    chosen=null;
  }catch(e){text(result,e.message)}finally{button.disabled=false}
});
load();"""


class RequestError(ValueError):
    pass


def secure_token(path: Path) -> str:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_uid != os.getuid():
        raise RequestError(f"Token must be owned by this user and 0600: {path}")
    token = path.read_text(encoding="ascii").strip()
    if len(token) < 32 or len(token) > 1024 or not token.isascii():
        raise RequestError("Token must be at least 32 ASCII characters")
    return token


def init_db(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart INTEGER NOT NULL CHECK (cart BETWEEN 1 AND 999999),
    requester TEXT NOT NULL CHECK (length(requester) BETWEEN 1 AND 64),
    client_hash TEXT NOT NULL,
    submitted_at INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','approved','scheduled','played','rejected')),
    scheduled_log TEXT,
    scheduled_at INTEGER,
    UNIQUE(id)
);
CREATE INDEX IF NOT EXISTS requests_queue_idx ON requests(status,submitted_at);
CREATE INDEX IF NOT EXISTS requests_repeat_idx ON requests(cart,submitted_at);
CREATE INDEX IF NOT EXISTS requests_client_idx ON requests(client_hash,submitted_at);
""")
    db.commit()


def catalog_ids(path: Path, allowed_groups: frozenset[str]) -> set[int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RequestError("Catalog must be a JSON array")
    ids = set()
    for row in data:
        if not isinstance(row, dict):
            raise RequestError("Invalid catalog row")
        group = row.get("group")
        cart = row.get("cart")
        if group in allowed_groups and type(cart) is int and 1 <= cart <= 999999:
            ids.add(cart)
    return ids


class Store:
    def __init__(self, database: Path):
        self.database = database
        self.lock = threading.Lock()
        database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if database.is_symlink():
            raise RequestError("Refusing symlinked database")
        with self.connect() as db:
            init_db(db)
        if database.exists():
            os.chmod(database, 0o600)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database, timeout=5, isolation_level=None)

    def submit(self, cart: int, requester: str, client_id: str,
               eligible: set[int], auto_approve: bool = True,
               now: int | None = None) -> dict:
        now = int(time.time()) if now is None else now
        if type(cart) is not int or cart not in eligible:
            raise RequestError("Cart is unavailable or not request-eligible")
        if (not isinstance(requester, str) or not 1 <= len(requester) <= 64
                or re.search(r"[\x00-\x1f\x7f]", requester)):
            raise RequestError("Invalid requester name (1-64 characters)")
        if not re.fullmatch(r"[a-f0-9]{64}", client_id):
            raise RequestError("Invalid client identity")
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                "SELECT COUNT(*) FROM requests WHERE client_hash=? AND submitted_at>?",
                (client_id, now - 3600)).fetchone()[0]
            if count >= MAX_REQUESTS_PER_HOUR:
                raise RequestError("Hourly request limit exceeded")
            recent = db.execute(
                "SELECT id FROM requests WHERE cart=? AND submitted_at>? "
                "AND status NOT IN ('rejected') LIMIT 1",
                (cart, now - MIN_REPEAT_SECONDS)).fetchone()
            if recent:
                raise RequestError("That song was requested recently")
            status = "approved" if auto_approve else "pending"
            cur = db.execute(
                "INSERT INTO requests(cart,requester,client_hash,submitted_at,status) "
                "VALUES (?,?,?,?,?)", (cart, requester.strip(), client_id, now, status))
            db.commit()
            return {"id": cur.lastrowid, "cart": cart, "status": status}

    def queue(self, status: str = "approved", limit: int = 100) -> list[dict]:
        if status not in ("approved", "pending", "scheduled", "played", "rejected"):
            raise RequestError("Invalid request status")
        if not 1 <= limit <= 500:
            raise RequestError("Invalid request limit")
        with self.lock, self.connect() as db:
            rows = db.execute(
                "SELECT id,cart,requester,submitted_at,status,scheduled_log "
                "FROM requests WHERE status=? ORDER BY submitted_at,id LIMIT ?",
                (status, limit)).fetchall()
        return [dict(zip(("id","cart","requester","submitted_at","status","scheduled_log"), row))
                for row in rows]

    def approve(self, request_id: int, status: str) -> bool:
        if status not in ("approved", "rejected"):
            raise RequestError("Admin can only approve or reject")
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "UPDATE requests SET status=? WHERE id=? AND status='pending'",
                (status, request_id))
            db.commit()
            return cursor.rowcount == 1

    def scheduled(self, ids: list[int], log: str, when: int | None = None) -> int:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", log):
            raise RequestError("Invalid log name")
        if len(ids) != len(set(ids)):
            raise RequestError("Duplicate request IDs")
        when = int(time.time()) if when is None else when
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = 0
            for request_id in ids:
                cursor = db.execute(
                    "UPDATE requests SET status='scheduled',scheduled_log=?,scheduled_at=? "
                    "WHERE id=? AND status='approved'",
                    (log, when, request_id))
                if cursor.rowcount != 1:
                    raise RequestError(f"Request {request_id} not in approved state")
                count += 1
            db.commit()
            return count


def identity_hash(ip: str, secret: str) -> str:
    import hashlib
    addr = str(ipaddress.ip_address(ip))
    return hmac.new(secret.encode("ascii"), addr.encode("ascii"), hashlib.sha256).hexdigest()


class RequestServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store: Store, listener_token: str, admin_token: str,
                 catalog: Path, groups: frozenset[str], auto_approve: bool,
                 public_portal: bool = False):
        super().__init__(address, RequestHandler)
        self.store, self.listener_token, self.admin_token = store, listener_token, admin_token
        self.catalog, self.groups, self.auto_approve = catalog, groups, auto_approve
        self.public_portal = public_portal


class RequestHandler(BaseHTTPRequestHandler):
    server: RequestServer

    def log_message(self, fmt, *args):
        # No request bodies, authorization, names, or URL query strings.
        print(f"request-api [{self.address_string()}] {fmt % args}", file=sys.stderr)

    def response(self, code: int, obj: dict | list):
        data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, role: str) -> bool:
        expected = self.server.admin_token if role == "admin" else self.server.listener_token
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied.encode("utf-8"),
                                   ("Bearer " + expected).encode("utf-8"))

    def payload(self) -> dict:
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise RequestError("Expected application/json")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise RequestError("Invalid Content-Length") from exc
        if size < 1 or size > MAX_BODY:
            raise RequestError("JSON body too large or empty")
        body = json.loads(self.rfile.read(size))
        if not isinstance(body, dict):
            raise RequestError("Expected JSON object")
        return body

    def static(self, content: str, kind: str, content_security: str):
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", content_security)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def public_csrf(self, hour: int) -> str:
        return hmac.new(self.server.admin_token.encode("ascii"),
                        f"public:{self.client_address[0]}:{hour}".encode("ascii"),
                        __import__("hashlib").sha256).hexdigest()

    def public_catalog(self):
        path = self.server.catalog
        state = path.lstat()
        if (not stat.S_ISREG(state.st_mode) or state.st_size > 16 * 1024 * 1024 or
                state.st_uid != os.getuid()):
            raise RequestError("Request catalog is not safe to publish")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise RequestError("Invalid request catalog")
        safe = []
        for row in rows:
            if not isinstance(row, dict) or row.get("group") not in self.server.groups:
                continue
            cart = row.get("cart")
            if type(cart) is not int or not 1 <= cart <= 999999:
                continue
            safe.append({"cart": cart, "title": str(row.get("title") or "")[:255],
                         "artist": str(row.get("artist") or "")[:255]})
            if len(safe) >= 10000:
                break
        self.response(200, {"songs": safe, "csrf": self.public_csrf(int(time.time() // 3600))})

    def do_GET(self):
        try:
            path = urlsplit(self.path)
            if path.path == "/healthz":
                return self.response(200, {"status":"ok"})
            if self.server.public_portal and not path.query:
                csp = "default-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; script-src 'self'; style-src 'self'; connect-src 'self'"
                if path.path == "/requests":
                    return self.static(PUBLIC_HTML, "text/html; charset=utf-8", csp)
                if path.path == "/requests/style.css":
                    return self.static(PUBLIC_CSS, "text/css; charset=utf-8", csp)
                if path.path == "/requests/app.js":
                    return self.static(PUBLIC_JS, "text/javascript; charset=utf-8", csp)
                if path.path == "/api/v1/public/catalog":
                    return self.public_catalog()
            if path.path == "/api/v1/requests":
                if not self.authorized("admin"):
                    return self.response(401, {"error":"unauthorized"})
                if path.query:
                    raise RequestError("Query parameters are not supported")
                return self.response(200, {"requests":self.server.store.queue()})
            return self.response(404, {"error":"not found"})
        except (RequestError, OSError, ValueError) as exc:
            return self.response(400, {"error":str(exc)})

    def do_POST(self):
        try:
            path = urlsplit(self.path)
            if path.query:
                raise RequestError("Query parameters are not supported")
            if path.path == "/api/v1/public/requests" and self.server.public_portal:
                payload = self.payload()
                if set(payload) != {"cart", "requester", "csrf"}:
                    raise RequestError("Expected cart, requester and CSRF token")
                submitted_csrf = payload["csrf"]
                hour = int(time.time() // 3600)
                if (not isinstance(submitted_csrf, str) or
                        not any(hmac.compare_digest(submitted_csrf, self.public_csrf(t))
                                for t in (hour, hour - 1))):
                    return self.response(403, {"error":"Invalid or expired request session"})
                eligible = catalog_ids(self.server.catalog, self.server.groups)
                client_hash = identity_hash(self.client_address[0], self.server.admin_token)
                row = self.server.store.submit(
                    payload["cart"], payload["requester"], client_hash,
                    eligible, auto_approve=False)
                return self.response(202, row)
            if path.path == "/api/v1/requests":
                if not self.authorized("listener"):
                    return self.response(401, {"error":"unauthorized"})
                payload = self.payload()
                if set(payload) != {"cart","requester"}:
                    raise RequestError("Expected cart and requester only")
                eligible = catalog_ids(self.server.catalog, self.server.groups)
                client_hash = identity_hash(self.client_address[0], self.server.admin_token)
                row = self.server.store.submit(
                    payload["cart"], payload["requester"], client_hash,
                    eligible, self.server.auto_approve)
                return self.response(202, row)
            m = re.fullmatch(r"/api/v1/admin/requests/([0-9]{1,15})/(approve|reject)",path.path)
            if m:
                if not self.authorized("admin"):
                    return self.response(401, {"error":"unauthorized"})
                if self.headers.get("Content-Length","0") not in ("0",""):
                    raise RequestError("No body expected")
                new_status = "approved" if m.group(2) == "approve" else "rejected"
                ok = self.server.store.approve(int(m.group(1)), new_status)
                return self.response(200 if ok else 409, {"changed":ok, "status":new_status})
            return self.response(404, {"error":"not found"})
        except (RequestError, OSError, ValueError, json.JSONDecodeError) as exc:
            return self.response(400, {"error":str(exc)})


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database",type=Path,required=True)
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--group",action="append",required=True)
    p.add_argument("--listener-token-file",type=Path,required=True)
    p.add_argument("--admin-token-file",type=Path,required=True)
    p.add_argument("--listen",default="127.0.0.1")
    p.add_argument("--port",type=int,default=8787)
    p.add_argument("--moderated",action="store_true")
    p.add_argument("--public-portal",action="store_true",
                   help="Serve an uncredentialed listener page on loopback (requests always moderated)")
    args=p.parse_args()
    if args.listen not in ("127.0.0.1","::1"):
        raise RequestError("Only loopback binding supported; use a secured reverse proxy")
    if not 1024<=args.port<=65535 or not args.catalog.is_file():
        raise RequestError("Invalid listener port or catalog")
    groups=frozenset(args.group)
    if not groups or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,9}",g) for g in groups):
        raise RequestError("Invalid groups")
    listener=secure_token(args.listener_token_file)
    admin=secure_token(args.admin_token_file)
    if hmac.compare_digest(listener,admin):
        raise RequestError("Listener and admin tokens must differ")
    store=Store(args.database)
    server=RequestServer((args.listen,args.port),store,listener,admin,
                         args.catalog,groups,not args.moderated,args.public_portal)
    print(f"Rivendell request intake listening on {args.listen}:{args.port}",flush=True)
    server.serve_forever()
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (RequestError,OSError,ValueError) as e:
        print(f"ERROR: {e}",file=sys.stderr)
        raise SystemExit(1)
