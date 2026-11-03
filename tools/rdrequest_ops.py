#!/usr/bin/python3
"""Local RDAirPlay request-console bridge; never starts playback itself.

JSON stdout allows the on-air Qt dialog to show requesters, moderate and
reserve a unique approved request before native RDLogPlay inserts the cart.
Only local user-readable SQLite/catalog paths are accepted.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import time

from rdrequests import RequestError, Store
from rdlive import LiveError, claim, eligible_window, load_ledger, status

STATE = Path.home() / ".local/state/rivendell-complete"
DATABASE = STATE / "requests.sqlite"
CATALOG = STATE / "request-catalog.json"
PLAN_DIR = STATE / "plans"


class ConsoleError(RuntimeError):
    pass


def owned_regular(path: Path, maximum: int) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ConsoleError(f"Request state has unsafe ownership: {path.name}")
    if info.st_mode & 0o077:
        raise ConsoleError(f"Request state permissions too broad: {path.name}")
    if info.st_size > maximum:
        raise ConsoleError(f"Request state too large: {path.name}")


def playable() -> dict[int, dict]:
    owned_regular(CATALOG, 64 * 1024 * 1024)
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ConsoleError("Request catalog must be an array")
    rows: dict[int, dict] = {}
    for item in data:
        if not isinstance(item, dict) or type(item.get("cart")) is not int:
            raise ConsoleError("Invalid request catalog")
        cart = item["cart"]
        if cart in rows:
            raise ConsoleError("Duplicate cart in request catalog")
        if not 1 <= cart <= 999999:
            raise ConsoleError("Invalid cart number")
        rows[cart] = item
    return rows


def open_store() -> Store:
    if not DATABASE.is_file():
        raise ConsoleError("Listener intake is not initialized; configure requests first")
    owned_regular(DATABASE, 1024 * 1024 * 1024)
    return Store(DATABASE)


def list_requests(store: Store, catalog: dict[int, dict]) -> dict:
    rows = [*store.queue("pending", 100), *store.queue("approved", 100)]
    rows.sort(key=lambda entry: (entry["submitted_at"], entry["id"]))
    result = []
    for row in rows[:200]:
        track = catalog.get(int(row["cart"]), {})
        result.append({
            "id": row["id"], "cart": row["cart"],
            "requester": row["requester"], "status": row["status"],
            "submitted_at": row["submitted_at"],
            "title": str(track.get("title") or "Unknown title")[:255],
            "artist": str(track.get("artist") or "Unknown artist")[:255],
        })
    return {"requests": result, "pending": sum(x["status"] == "pending" for x in result),
            "approved": sum(x["status"] == "approved" for x in result)}


def validated_loaded_log(ledger: Path, log_name: str) -> None:
    if not isinstance(log_name, str) or not __import__("re").fullmatch(
            r"[A-Za-z0-9_-]{1,64}", log_name):
        raise ConsoleError("A loaded Rivendell main log name is required")
    data = json.loads(ledger.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("log_name") != log_name:
        raise ConsoleError("Loaded main log does not match the protected station schedule")


def eligible(store: Store, catalog: dict[int, dict],
             *, loaded_log: str = "", now: datetime | None = None,
             plan_dir: Path = PLAN_DIR) -> dict | None:
    now = now or datetime.now().astimezone()
    ledger = plan_dir / (now.date().isoformat() + ".plan.json")
    hard = load_ledger(ledger, now)
    validated_loaded_log(ledger, loaded_log)
    for row in store.queue("approved", 100):
        track = catalog.get(int(row["cart"]))
        if not track:
            continue
        if eligible_window(now, int(track.get("length_ms") or 0), hard):
            return {"id": row["id"], "cart": row["cart"],
                    "title": track.get("title"), "artist": track.get("artist")}
    return None


def request_eligible(store: Store, request_id: int,
                     catalog: dict[int, dict], loaded_log: str = "",
                     plan_dir: Path = PLAN_DIR) -> tuple[int, dict]:
    candidates = [row for row in store.queue("approved", 500) if row["id"] == request_id]
    if not candidates:
        raise ConsoleError("Request is no longer approved")
    selected = candidates[0]
    cart = int(selected["cart"])
    track = catalog.get(cart)
    if track is None:
        raise ConsoleError("Requested cart is missing from the playable music catalog")
    now = datetime.now().astimezone()
    ledger = plan_dir / (now.date().isoformat() + ".plan.json")
    hard = load_ledger(ledger, now)
    validated_loaded_log(ledger, loaded_log)
    if not eligible_window(now, int(track.get("length_ms") or 0), hard):
        raise ConsoleError("Request would violate the protected on-air timing window")
    return cart, track


def reserve(store: Store, request_id: int, catalog: dict[int, dict],
            loaded_log: str = "", plan_dir: Path = PLAN_DIR) -> dict:
    cart, track = request_eligible(store, request_id, catalog,
                                   loaded_log=loaded_log, plan_dir=plan_dir)
    with store.connect() as db:
        if not claim(db, request_id, cart, int(time.time())):
            raise ConsoleError("Request already claimed or state changed")
    return {"id": request_id, "cart": cart,
            "title": track.get("title"), "status": "reserved"}


def complete(store: Store, request_id: int, cart: int, success: bool) -> dict:
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT cart,status FROM live_dispatches WHERE request_id=?",
            (request_id,)).fetchone()
        if row is None or int(row[0]) != cart or row[1] != "sending":
            raise ConsoleError("Request was not reserved for this cart")
        if success:
            changed = db.execute(
                "UPDATE requests SET status='scheduled', scheduled_log=?, scheduled_at=? "
                "WHERE id=? AND cart=? AND status='approved'",
                ("RDAIRPLAY", int(time.time()), request_id, cart),
            )
            if changed.rowcount != 1:
                db.rollback()
                raise ConsoleError("Request changed after reserve; manual reconciliation required")
            db.execute(
                "UPDATE live_dispatches SET status='acknowledged' WHERE request_id=?",
                (request_id,))
        else:
            db.execute(
                "UPDATE live_dispatches SET status='delivery_unknown' WHERE request_id=?",
                (request_id,))
        db.commit()
    return {"id": request_id, "cart": cart,
            "status": "queued" if success else "delivery_unknown"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",
                        choices=("list", "approve", "reject", "eligible", "reserve",
                                 "complete", "uncertain"))
    parser.add_argument("--id", type=int)
    parser.add_argument("--cart", type=int)
    parser.add_argument("--plan-dir", type=Path, default=PLAN_DIR)
    parser.add_argument("--loaded-log", default="",
                        help="Actual RDAirPlay main log name required for queueing")
    args = parser.parse_args(argv)
    if args.id is not None and not 1 <= args.id <= 2**63 - 1:
        raise ConsoleError("Invalid request ID")
    if args.cart is not None and not 1 <= args.cart <= 999999:
        raise ConsoleError("Invalid cart number")
    if args.action in ("approve", "reject", "reserve", "complete", "uncertain") and args.id is None:
        parser.error("--id is required")
    if args.action in ("complete", "uncertain") and args.cart is None:
        parser.error("--cart is required")
    store = open_store()
    catalog = playable()
    if args.action == "list":
        result = list_requests(store, catalog)
    elif args.action in ("approve", "reject"):
        ok = store.approve(args.id, "approved" if args.action == "approve" else "rejected")
        if not ok:
            raise ConsoleError("Request is not pending")
        result = {"id": args.id, "status": "approved" if ok and args.action == "approve" else "rejected"}
    elif args.action == "eligible":
        candidate = eligible(store, catalog, loaded_log=args.loaded_log,
                             plan_dir=args.plan_dir)
        result = {"candidate": candidate, "eligible": candidate is not None}
    elif args.action == "reserve":
        result = reserve(store, args.id, catalog,
                         loaded_log=args.loaded_log, plan_dir=args.plan_dir)
    else:
        result = complete(store, args.id, args.cart, args.action == "complete")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConsoleError, RequestError, LiveError, OSError, ValueError,
            KeyError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
