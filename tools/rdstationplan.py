#!/usr/bin/env python3
"""24-hour radio schedule assembler with fixed IDs, paid spots and requests.

Runs OFFLINE: produces a Rivendell log for inspection and later use.
Never overwrites an existing log, original NAS music, or on-air schedule.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import random
import re
import shutil
import sqlite3
import subprocess
import sys
from typing import Any

from rdsmartclock import (Event, Track, PlanError, choose, commands,
                          load_catalog_json, remember, settings)

HOUR = 3600000
DAY = 24 * HOUR


@dataclass(frozen=True)
class Planned:
    events: list[Event]
    request_ids: list[int]
    segment_gaps: list[int]


def cart_spec(item: dict, label: str) -> tuple[int, int]:
    if not isinstance(item, dict):
        raise PlanError(f"{label} must be an object")
    cart = item.get("cart")
    length = item.get("duration_ms")
    if type(cart) is not int or not 1 <= cart <= 999999:
        raise PlanError(f"{label}.cart must be 1..999999")
    if type(length) is not int or not 500 <= length <= HOUR:
        raise PlanError(f"{label}.duration_ms must be 500..3600000")
    return cart, length


def validate(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise PlanError("Configuration must be a JSON object")
    cart, _ = cart_spec(cfg.get("top_hour"), "top_hour")
    # Reuse the original validated rotation/separation schema while
    # accepting the richer {cart,duration_ms} station-ID declaration.
    settings({**cfg, "top_hour_cart":cart})
    for key in ("max_segment_gap_ms", "max_requests_per_hour"):
        val = cfg.get(key, 0)
        if type(val) is not int or val < 0 or val > (30000 if key == "max_segment_gap_ms" else 6):
            raise PlanError(f"{key} outside permitted range")
    breaks = cfg.get("breaks", [])
    if not isinstance(breaks, list) or len(breaks) > 20:
        raise PlanError("breaks must contain at most 20 slots")
    last = 0
    for i, item in enumerate(breaks):
        if not isinstance(item, dict):
            raise PlanError("break must be an object")
        minute = item.get("minute")
        if type(minute) is not int or not 1 <= minute <= 59 or minute <= last:
            raise PlanError("break minutes must strictly increase, between 1 and 59")
        last = minute
        spots = item.get("spots")
        if not isinstance(spots, list) or not 1 <= len(spots) <= 20:
            raise PlanError("Each break requires 1-20 spots")
        for j, spot in enumerate(spots):
            cart_spec(spot, f"breaks[{i}].spots[{j}]")
        end_ms = minute * 60000 + sum(int(x["duration_ms"]) for x in spots)
        next_minute = (breaks[i + 1]["minute"] if i + 1 < len(breaks) and
                       isinstance(breaks[i + 1], dict) else 60)
        if type(next_minute) is not int or end_ms >= next_minute * 60000:
            raise PlanError("Spot break overruns the next hard event")
    if "fill_bed" in cfg:
        cart_spec(cfg["fill_bed"], "fill_bed")
    if "jingle" in cfg:
        cart_spec(cfg["jingle"], "jingle")
        jingle_every = cfg.get("jingle_every", 4)
        if type(jingle_every) is not int or not 1 <= jingle_every <= 25:
            raise PlanError("jingle_every must be 1..25")
    return cfg


def approved_requests(database: Path | None, eligible: set[int]) -> list[dict]:
    if database is None:
        return []
    if database.is_symlink() or not database.is_file():
        raise PlanError("Request database unavailable or symlinked")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5) as db:
        rows = db.execute(
            "SELECT id,cart,submitted_at FROM requests WHERE status='approved' "
            "ORDER BY submitted_at,id LIMIT 500").fetchall()
    # Exclude station IDs, spots, or unavailable audio even if a stale
    # request record was previously approved.
    return [{"id": int(rid), "cart":int(cart)}
            for rid, cart, _ in rows if int(cart) in eligible]


def _choose_song(pools: dict[str, list[Track]], cfg: dict, requests: list[dict],
                 used_requests: set[int], now: int, budget: int,
                 last: dict, rng: random.Random, rotation: list[str],
                 pos: list[int], requests_this_hour: int,
                 by_cart: dict[int, Track]) -> tuple[Track | None, int | None]:
    if requests_this_hour < cfg.get("max_requests_per_hour", 2):
        for row in requests:
            if row["id"] in used_requests:
                continue
            t = by_cart.get(row["cart"])
            if t and t.length_ms <= budget and _eligible(t, now, last, cfg):
                return t, row["id"]
    # Try one complete rotation pass before declaring the segment blocked.
    for _ in range(len(rotation)):
        group = rotation[pos[0] % len(rotation)]
        pos[0] += 1
        t = choose(pools[group], now, budget, last, cfg, rng,
                   close=(budget <= 360000))
        if t is not None:
            return t, None
    return None, None


def _eligible(track: Track, now: int, last: dict, cfg: dict) -> bool:
    from rdsmartclock import eligible
    return eligible(track, now, last, cfg)


def assemble(catalog: list[Track], cfg: dict, day: date,
             requests: list[dict] | None = None) -> Planned:
    validate(cfg)
    pools: dict[str,list[Track]] = {}
    for t in catalog:
        pools.setdefault(t.group, []).append(t)
    for group in cfg["rotation"]:
        if group not in pools:
            raise PlanError(f"Missing rotation group: {group}")
    by_cart = {t.cart: t for t in catalog}
    requests = requests or []
    if any(r["cart"] not in by_cart for r in requests):
        raise PlanError("Request cart is not in the music catalog")
    ids = set()
    history: dict = {}
    results: list[Event] = []
    gaps: list[int] = []
    pos = [0]
    rng = random.Random(f"RivendellComplete:{day.isoformat()}:{cfg['service']}")
    idcart, idlen = cart_spec(cfg["top_hour"], "top_hour")
    bed = cart_spec(cfg["fill_bed"], "fill_bed") if "fill_bed" in cfg else None
    jingle = cart_spec(cfg["jingle"], "jingle") if "jingle" in cfg else None
    max_gap = cfg.get("max_segment_gap_ms", 1000)
    max_requests = cfg.get("max_requests_per_hour", 2)
    song_counter = 0

    for hour in range(24):
        start = hour * HOUR
        results.append(Event(idcart, start, idlen, "top-hour-id", True))
        anchors: list[tuple[int,list[tuple[int,int]],str]] = []
        for br in cfg.get("breaks", []):
            anchors.append((start + br["minute"]*60000,
                            [cart_spec(x, "spot") for x in br["spots"]], "spots"))
        anchors.append((start + HOUR, [], "end"))
        now = start + idlen
        requests_this_hour = 0
        for anchor, break_carts, kind in anchors:
            if now >= anchor:
                raise PlanError(f"An event overruns the protected break at {anchor}")
            n = 0
            while anchor - now > max_gap:
                available = anchor - now
                if n > 100:
                    raise PlanError("Excessive music events: possible zero-duration loop")
                track, rid = _choose_song(pools,cfg,requests,ids,now,available,
                                          history,rng,cfg["rotation"],pos,requests_this_hour,
                                          by_cart)
                if track is None:
                    break
                results.append(Event(track.cart,now,track.length_ms,
                                     "request" if rid is not None else "music"))
                if rid is not None:
                    ids.add(rid)
                    requests_this_hour += 1
                remember(track,now,history)
                now += track.length_ms
                song_counter += 1
                n += 1
                if jingle and song_counter % cfg.get("jingle_every", 4) == 0:
                    if now + jingle[1] <= anchor:
                        results.append(Event(jingle[0],now,jingle[1],"jingle"))
                        now += jingle[1]
            gap = anchor - now
            if gap > max_gap:
                if bed is None:
                    raise PlanError(
                        f"Unfillable {gap}ms gap before {anchor // 60000:04d}m: "
                        "add eligible short songs, a fill bed, or adjust timing")
                if bed[1] < gap:
                    raise PlanError(
                        f"Fill bed too short for {gap}ms until the hard event")
                # A deliberately timed bed is cut by the next hard event.
                # Music is NEVER deliberately cut by the offline scheduler.
                results.append(Event(bed[0],now,gap,"fill-bed"))
                now = anchor
                gap = 0
            gaps.append(gap)
            if kind == "spots":
                for idx, (cart,duration) in enumerate(break_carts):
                    results.append(Event(cart,now,duration,
                                         "spot",idx == 0))
                    now += duration
            else:
                # The next hour's protected ID is the hard anchor.
                now = anchor
    # Resolve explicitly requested IDs in insertion order, not music ordering.
    selected=[row["id"] for row in requests if row["id"] in ids]
    if any(x.start_ms < 0 or x.start_ms >= DAY for x in results):
        raise PlanError("Event outside broadcast day")
    hard=[e.start_ms for e in results if e.hard]
    if hard != sorted(hard) or len([e for e in results if e.kind=="top-hour-id"])!=24:
        raise PlanError("Invalid legal ID or spot chronology")
    return Planned(results,selected,gaps)


def main(argv=None) -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config",type=Path,required=True)
    ap.add_argument("--catalog",type=Path,required=True)
    ap.add_argument("--requests-db",type=Path)
    ap.add_argument("--date",type=date.fromisoformat,required=True)
    ap.add_argument("--log-name",required=True)
    ap.add_argument("--commit",action="store_true")
    ap.add_argument("--report-json",type=Path,
                    help="Save event ledger JSON, exclusively creating new file")
    args=ap.parse_args(argv)
    cfg=validate(json.loads(args.config.read_text(encoding="utf-8")))
    catalog=load_catalog_json(args.catalog)
    approved=approved_requests(args.requests_db,{t.cart for t in catalog})
    planned=assemble(catalog,cfg,args.date,approved)
    log_commands=commands(planned.events,cfg["service"],args.date,args.log_name)
    print(f"Scheduled {len(planned.events)} events, 24 IDs, "
          f"{len(planned.request_ids)} requests; maximum planned gap "
          f"{max(planned.segment_gaps,default=0)}ms",file=sys.stderr)
    report=[{"cart":e.cart,"start_ms":e.start_ms,"length_ms":e.length_ms,
             "kind":e.kind,"hard":e.hard} for e in planned.events]
    if args.report_json and (args.report_json.exists() or args.report_json.is_symlink()):
        raise PlanError("Report exists; refusing overwrite")
    if not args.commit:
        if args.report_json:
            if args.report_json.name.endswith(".plan.json"):
                raise PlanError("Uncommitted preview cannot be named as a live plan")
            args.report_json.write_text(json.dumps(report,indent=2)+"\n")
        sys.stdout.write(log_commands)
        print("DRY RUN: no logs or request statuses changed",file=sys.stderr)
        return 0
    if shutil.which("rdclilogedit") is None:
        raise PlanError("rdclilogedit unavailable")
    # All requests are incorporated into an OFFLINE unique new log, never
    # into the currently playing queue, so hard spots and IDs remain protected.
    result=subprocess.run(["rdclilogedit","-n"],input=log_commands,
                          capture_output=True,text=True,timeout=240,check=False)
    if result.returncode or result.stderr.strip():
        raise PlanError("Log editor reported an error; inspect partial log "
                        "before retrying: "+result.stderr.strip()[-1500:])
    if args.requests_db and planned.request_ids:
        from rdrequests import Store
        Store(args.requests_db).scheduled(planned.request_ids,args.log_name)
    if args.report_json:
        # A plan is eligible for live insertion ONLY after its corresponding
        # Rivendell log has actually been committed successfully.
        data=(json.dumps(report,indent=2)+"\n").encode("utf-8")
        import os
        fd=os.open(args.report_json,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    print(f"Created new offline Rivendell log {args.log_name}",file=sys.stderr)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (PlanError,OSError,ValueError,KeyError,sqlite3.Error,
            subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        raise SystemExit(1)
