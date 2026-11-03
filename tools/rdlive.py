#!/usr/bin/env python3
"""Conservative live request dispatcher for Rivendell Complete.

Uses authenticated on-air intake queue, a *current-day* protected schedule
ledger, and Rivendell's RML PX echo acknowledgement. Refuses uncertain
delivery; never repeats an ambiguous send without manual reconciliation.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import time

from rdrequests import Store

ECHO_PORT=5858
REPLY_PORT=5860
SAFE_RESERVE_MS=390000
DAY_MS=86400000


class LiveError(RuntimeError):
    pass


def send_px(cart: int, machine: int = 1, timeout: float = 3.0) -> bool:
    """True=positive Rivendell RML acknowledgment, False=explicit rejection.

    Exceptions mean delivery unknown (including no acknowledgment). These
    MUST NOT be retried automatically.
    """
    if type(cart) is not int or not 1 <= cart <= 999999:
        raise LiveError("Invalid cart")
    if type(machine) is not int or not 1 <= machine <= 3:
        raise LiveError("Invalid Rivendell log machine")
    message=f"PX {machine} {cart} 0 SEGUE!"
    expected_prefix=f"PX {machine} {cart} 0 SEGUE "
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        try:
            sock.bind(("127.0.0.1",REPLY_PORT))
        except OSError as exc:
            raise LiveError("RML acknowledgment port 5860 unavailable") from exc
        sock.settimeout(timeout)
        sent=sock.sendto(message.encode("ascii"),("127.0.0.1",ECHO_PORT))
        if sent!=len(message):
            raise LiveError("Partial RML transmission; delivery unknown")
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            sock.settimeout(max(0.05,deadline-time.monotonic()))
            try:
                raw,peer=sock.recvfrom(2048)
            except socket.timeout:
                break
            if peer[0]!="127.0.0.1":
                continue
            payload=raw.decode("ascii",errors="replace").strip()
            if payload==expected_prefix+"+!":
                return True
            if payload==expected_prefix+"-!":
                return False
        raise LiveError("Timed out waiting for a matching RML acknowledgment; delivery unknown")


def load_ledger(path: Path, current: datetime) -> list[int]:
    if path.is_symlink() or not path.is_file():
        raise LiveError("Missing trusted current-day station ledger")
    if path.name!=f"{current.date().isoformat()}.plan.json":
        raise LiveError("Plan ledger date does not match current station date")
    data=json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data,dict):
        name=data.get("log_name")
        if not isinstance(name,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",name):
            raise LiveError("Protected ledger missing validated log identity")
        data=data.get("events")
    if not isinstance(data,list) or len(data)<24:
        raise LiveError("No valid 24-hour station plan")
    times=[]
    ids=0
    for row in data:
        if not isinstance(row,dict):
            raise LiveError("Malformed plan row")
        ms=row.get("start_ms")
        if type(ms) is not int or not 0<=ms<DAY_MS:
            raise LiveError("Invalid event time")
        if row.get("kind")=="top-hour-id":
            ids+=1
        if row.get("hard") is True:
            times.append(ms)
    if ids!=24 or len(times)<24 or times!=sorted(times):
        raise LiveError("Current day plan lacks protected legal IDs")
    return times


def eligible_window(now: datetime, duration_ms: int, hard_times: list[int]) -> bool:
    if not 500<=duration_ms<=900000:
        return False
    current_ms=(now.hour*3600+now.minute*60+now.second)*1000+now.microsecond//1000
    upcoming=[t for t in hard_times if t>current_ms]
    if not upcoming:
        upcoming=[DAY_MS]
    return upcoming[0]-current_ms >= duration_ms+SAFE_RESERVE_MS


def claim(conn: sqlite3.Connection, request_id: int, cart: int, when: int) -> bool:
    conn.execute("""CREATE TABLE IF NOT EXISTS live_dispatches(
      request_id INTEGER PRIMARY KEY, cart INTEGER NOT NULL,
      started_at INTEGER NOT NULL, status TEXT NOT NULL
    )""")
    conn.execute("BEGIN IMMEDIATE")
    row=conn.execute(
        "SELECT id FROM requests WHERE id=? AND cart=? AND status='approved'",
        (request_id,cart)).fetchone()
    if row is None:
        conn.rollback()
        return False
    try:
        conn.execute(
            "INSERT INTO live_dispatches(request_id,cart,started_at,status) "
            "VALUES (?,?,?,'sending')", (request_id,cart,when))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False


def status(conn: sqlite3.Connection, request_id: int, state: str) -> None:
    if state not in ("acknowledged","rejected","delivery_unknown"):
        raise LiveError("Invalid dispatch state")
    conn.execute("UPDATE live_dispatches SET status=? WHERE request_id=?",
                 (state,request_id))
    conn.commit()


def one_pass(store: Store, catalog: Path, ledger: Path, now: datetime,
             *, live: bool, machine: int = 1) -> dict:
    hard=load_ledger(ledger,now)
    rows=json.loads(catalog.read_text(encoding="utf-8"))
    if not isinstance(rows,list):
        raise LiveError("Invalid catalog")
    tracks={}
    for row in rows:
        if isinstance(row,dict) and type(row.get("cart")) is int:
            tracks[row["cart"]]=row
    queue=store.queue("approved")
    for req in queue:
        track=tracks.get(req["cart"])
        if track is None or not eligible_window(now,int(track.get("length_ms") or 0),hard):
            continue
        if not live:
            return {"status":"eligible-dry-run","request_id":req["id"],"cart":req["cart"]}
        # Do not send when the studio application is not actually running.
        if subprocess.run(["pgrep","-x","rdairplay"],capture_output=True,check=False).returncode:
            raise LiveError("RDAirPlay is not running")
        with store.connect() as conn:
            if not claim(conn,req["id"],req["cart"],int(now.timestamp())):
                continue
            try:
                accepted=send_px(req["cart"],machine)
            except (LiveError,OSError) as exc:
                status(conn,req["id"],"delivery_unknown")
                raise LiveError(f"Request {req['id']} needs manual reconciliation: {exc}") from exc
            if not accepted:
                status(conn,req["id"],"rejected")
                return {"status":"rejected-by-rivendell","request_id":req["id"]}
            status(conn,req["id"],"acknowledged")
            store.scheduled([req["id"]],f"LIVE{now:%Y%m%d}")
            return {"status":"rml-acknowledged","request_id":req["id"],"cart":req["cart"]}
    return {"status":"no-eligible-requests"}


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database",type=Path,required=True)
    parser.add_argument("--catalog",type=Path,required=True)
    parser.add_argument("--plan-dir",type=Path,required=True)
    parser.add_argument("--machine",type=int,default=1)
    parser.add_argument("--live",action="store_true",
                        help="Actually send guarded, acknowledged RML PX commands")
    parser.add_argument("--poll-seconds",type=int,default=15)
    parser.add_argument("--once",action="store_true")
    args=parser.parse_args(argv)
    if not 1<=args.machine<=3 or not 5<=args.poll_seconds<=300:
        raise LiveError("Invalid log machine or poll frequency")
    store=Store(args.database)
    while True:
        now=datetime.now().astimezone()
        ledger=args.plan_dir/f"{now.date().isoformat()}.plan.json"
        result=one_pass(store,args.catalog,ledger,now,live=args.live,machine=args.machine)
        print(json.dumps(result),flush=True)
        if args.once:
            break
        time.sleep(args.poll_seconds)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (LiveError,OSError,ValueError,sqlite3.Error,subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        raise SystemExit(1)
