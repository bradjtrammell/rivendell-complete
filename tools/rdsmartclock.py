#!/usr/bin/env python3
"""Generate a protected Rivendell log with music rotation and backtimed hourly IDs.

This is an *offline* backtiming planner, not a live playlist rewriter.
Output is rdclilogedit(1) commands. Dry-run by default.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
from typing import Any

GROUP_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,9}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DAY_MS = 86400000
HOUR_MS = 3600000


class PlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class Track:
    cart: int
    group: str
    title: str
    artist: str
    album: str
    length_ms: int

    @staticmethod
    def from_dict(obj: dict) -> "Track":
        track = Track(
            int(obj["cart"]), str(obj["group"]),
            str(obj["title"]).strip(), str(obj["artist"]).strip(),
            str(obj["album"]).strip(), int(obj["length_ms"]),
        )
        if not (1 <= track.cart <= 999999 and GROUP_RE.fullmatch(track.group)
                and 500 <= track.length_ms <= 24 * HOUR_MS
                and track.title and track.artist and track.album):
            raise PlanError(f"Invalid catalog row {obj!r}")
        return track


@dataclass(frozen=True)
class Event:
    cart: int
    start_ms: int
    length_ms: int
    kind: str
    hard: bool = False


def settings(config: dict) -> dict:
    if not isinstance(config, dict):
        raise PlanError("Configuration must be a JSON object")
    service = config.get("service", "")
    rotation = config.get("rotation", [])
    idcart = config.get("top_hour_cart")
    if not isinstance(service, str) or not GROUP_RE.fullmatch(service):
        raise PlanError("service must be a valid 1-10 character Rivendell service")
    if not isinstance(rotation, list) or not rotation or len(rotation) > 200:
        raise PlanError("rotation must be a nonempty list of category group names")
    if any(not isinstance(g, str) or not GROUP_RE.fullmatch(g) for g in rotation):
        raise PlanError("invalid rotation group")
    if type(idcart) is not int or not 1 <= idcart <= 999999:
        raise PlanError("top_hour_cart must be a valid cart number")
    for key, lower, upper in (
        ("artist_separation_minutes", 0, 24*60),
        ("album_separation_minutes", 0, 24*60),
        ("title_separation_minutes", 0, 24*60),
        ("max_hour_gap_ms", 0, 30000),
        ("safety_margin_ms", 0, 30000),
    ):
        value = config.get(key, 0)
        if type(value) is not int or not lower <= value <= upper:
            raise PlanError(f"{key} must be an integer between {lower} and {upper}")
    return config


def key(text: str) -> str:
    return " ".join(text.casefold().split())


def eligible(t: Track, now: int, last: dict, cfg: dict) -> bool:
    tests = (
        ("artist", t.artist, cfg.get("artist_separation_minutes", 120) * 60000),
        ("album", t.album, cfg.get("album_separation_minutes", 60) * 60000),
        ("title", t.title, cfg.get("title_separation_minutes", 1440) * 60000),
        ("cart", str(t.cart), 1440 * 60000),
    )
    for kind, name, period in tests:
        if period <= 0:
            continue
        previous = last.get((kind, key(name)))
        if previous is not None and now - previous < period:
            return False
    return True


def remember(t: Track, now: int, last: dict) -> None:
    for kind, name in (
        ("artist", t.artist), ("album", t.album),
        ("title", t.title), ("cart", str(t.cart))
    ):
        last[(kind, key(name))] = now


def choose(pool: list[Track], now: int, available: int, last: dict,
           cfg: dict, rng: random.Random, close: bool = False) -> Track | None:
    options = [t for t in pool
               if t.length_ms <= available
               and eligible(t, now, last, cfg)]
    if not options:
        return None
    if close:
        # Under six minutes from the hour, prefer the closest-fitting song.
        options.sort(key=lambda t: (available - t.length_ms, t.cart))
        shortlist = options[:min(4, len(options))]
        # A deterministic bias toward the best fit, without always using one song.
        return rng.choice(shortlist[:2])
    options.sort(key=lambda t: t.cart)
    return rng.choice(options)


def plan_day(catalog: list[Track], cfg: dict, day: date, id_length: int) -> list[Event]:
    settings(cfg)
    if not 500 <= id_length < 60000:
        raise PlanError("Top-hour ID duration must be 0.5-60 seconds")
    by_group: dict[str, list[Track]] = {}
    for t in catalog:
        by_group.setdefault(t.group, []).append(t)
    for g in cfg["rotation"]:
        if not by_group.get(g):
            raise PlanError(f"Empty music group: {g}")
    rng = random.Random(f"{day.isoformat()}::{cfg['service']}")
    chosen: list[Event] = []
    last: dict[tuple[str, str], int] = {}
    pos = 0
    cycle = cfg["rotation"]
    margin = cfg.get("safety_margin_ms", 5000)
    max_gap = cfg.get("max_hour_gap_ms", 12000)
    max_group_misses = len(cycle)
    for hour in range(24):
        hour_start = hour * HOUR_MS
        if hour == 0 and pos != 0:
            raise PlanError("Unexpected nonzero initial event count")
        chosen.append(Event(cfg["top_hour_cart"], hour_start, id_length, "top-hour", True))
        now = hour_start + id_length
        end = hour_start + HOUR_MS - margin
        failures = 0
        song_count = 0
        while end - now > max_gap:
            available = end - now
            group = cycle[pos % len(cycle)]
            candidates = by_group[group]
            # Short-track selection at the close is offline duration backtiming.
            close = available <= 360000
            track = choose(candidates, now, available, last, cfg, rng, close)
            pos += 1
            if track is None:
                failures += 1
                if failures >= max_group_misses:
                    raise PlanError(
                        f"No eligible song that fits hour {hour:02d}, "
                        f"remaining={available}ms; adjust categories, separation or gap")
                continue
            failures = 0
            chosen.append(Event(track.cart, now, track.length_ms, "music"))
            remember(track, now, last)
            now += track.length_ms
            song_count += 1
            if song_count > 120:
                raise PlanError("Excessively many items in one hour")
        if end - now > max_gap:
            raise PlanError(f"Hour {hour:02d} exceeds permitted gap")
    return chosen


def commands(events: list[Event], service: str, day: date, log_name: str) -> str:
    if not NAME_RE.fullmatch(log_name) or not GROUP_RE.fullmatch(service):
        raise PlanError("Invalid service or log name")
    lines = [
        f"new {log_name}",
        f"setservice {service}",
        f"setstartdate {day.isoformat()}",
        f"setenddate {day.isoformat()}",
        "setautorefresh no",
    ]
    for index, event in enumerate(events):
        lines.append(f"addcart {index} {event.cart}")
        lines.append(f"settrans {index} {'play' if event.hard else 'segue'}")
        if event.hard:
            hh = (event.start_ms // HOUR_MS) % 24
            lines.append(f"settime {index} hard {hh:02d}:00:00")
    lines.extend(["save", "bye"])
    return "\n".join(lines) + "\n"


def load_catalog_json(path: Path) -> list[Track]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, list):
        raise PlanError("Catalog must be a JSON array of tracks")
    rows = [Track.from_dict(x) for x in obj]
    numbers = [r.cart for r in rows]
    if len(set(numbers)) != len(numbers):
        raise PlanError("Duplicate cart numbers in catalog")
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--catalog", required=True, type=Path,
                   help="JSON array of carts, with group/title/artist/album/length_ms")
    p.add_argument("--date", required=True, type=date.fromisoformat)
    p.add_argument("--id-duration-ms", required=True, type=int,
                   help="Measured station ID cart duration")
    p.add_argument("--log-name", required=True, help="NEW unique Rivendell log name")
    p.add_argument("--commit", action="store_true",
                   help="Create a NEW Rivendell log via rdclilogedit (never overwrite)")
    args = p.parse_args(argv)
    cfg = settings(json.loads(args.config.read_text(encoding="utf-8")))
    tracks = load_catalog_json(args.catalog)
    events = plan_day(tracks, cfg, args.date, args.id_duration_ms)
    output = commands(events, cfg["service"], args.date, args.log_name)
    print(f"Generated {len(events)} events; 24 hard top-hour events.", file=sys.stderr)
    if not args.commit:
        print("DRY RUN only; pipe output to a file for inspection.", file=sys.stderr)
        sys.stdout.write(output)
        return 0
    if shutil.which("rdclilogedit") is None:
        raise PlanError("rdclilogedit not installed")
    # Never use this against a loaded/on-air log. This is an OFFLINE generator.
    # Fail closed on stderr as rdclilogedit can return success for command errors.
    result = subprocess.run(["rdclilogedit", "-n"], input=output,
                            capture_output=True, text=True, timeout=180,
                            check=False)
    if result.returncode or result.stderr.strip():
        raise PlanError("rdclilogedit reported an error; an incomplete log MAY "
                        "have been created. Inspect before retrying. "
                        + result.stderr.strip()[-2000:])
    print(f"Created log {args.log_name}; inspect it in RDLogEdit before air.", file=sys.stderr)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PlanError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
