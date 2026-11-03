#!/usr/bin/env python3
"""Register read-only NAS audio as Rivendell 4 CART/CUTS without copying media.

Requires: ffprobe, python3-pymysql. Run against a STOPPED test station first.
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass

SUPPORTED = {".mp3": "mp3", ".wav": "pcm", ".ogg": "vorbis"}
CUT_RE = re.compile(r"^([0-9]{6})_001[.]ref$")
INVALID = re.compile(r"[\x00-\x1f]")
CART_MAX = 999999


class ImportFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class Track:
    relative: str
    title: str
    artist: str
    album: str
    length_ms: int
    sample_rate: int
    channels: int
    bitrate: int
    coding: int


def media_path(root: Path, relative: str) -> Path:
    """Return a strictly contained existing regular file, resolving all links."""
    if not relative or INVALID.search(relative) or "\\" in relative:
        raise ImportFailure(f"Invalid relative path: {relative!r}")
    rpath = Path(relative)
    if rpath.is_absolute() or any(p in ("..", ".") for p in rpath.parts):
        raise ImportFailure(f"Escaping media path: {relative!r}")
    root = root.resolve(strict=True)
    target = (root / rpath).resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file() or target == root:
        raise ImportFailure(f"Not a contained regular file: {relative!r}")
    return target


def scan_paths(root: Path, limit: int | None = None):
    count = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(base) / d).is_symlink())
        for name in sorted(files):
            path = Path(base) / name
            if path.is_symlink() or path.suffix.lower() not in SUPPORTED:
                continue
            rel = path.relative_to(root).as_posix()
            try:
                media_path(root, rel)
            except (ImportFailure, OSError) as exc:
                print(f"SKIP {rel!r}: {exc}", file=sys.stderr)
                continue
            yield rel
            count += 1
            if limit is not None and count >= limit:
                return


def probe(root: Path, relative: str) -> Track:
    src = media_path(root, relative)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:format_tags=title,artist,album:"
         "stream=codec_name,codec_type,sample_rate,channels,bit_rate",
         "-of", "json", str(src)],
        capture_output=True, text=True, timeout=20, check=False,
    )
    if result.returncode:
        raise ImportFailure(f"ffprobe failed for {relative!r}: {result.stderr.strip()[:250]}")
    data = json.loads(result.stdout)
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if len(streams) != 1:
        raise ImportFailure(f"Expected one audio stream: {relative!r}")
    s = streams[0]
    codec = s.get("codec_name", "")
    ext = src.suffix.lower()
    if ext == ".mp3" and codec != "mp3":
        raise ImportFailure(f"Not actual MP3 data: {relative!r}")
    if ext == ".ogg" and codec != "vorbis":
        raise ImportFailure(f"Not Vorbis data: {relative!r}")
    if ext == ".wav" and codec not in ("pcm_s16le", "pcm_s24le"):
        raise ImportFailure(f"Unsupported WAV encoding {codec}: {relative!r}")
    try:
        duration = float(data["format"]["duration"])
        length = round(duration * 1000)
        rate = int(s["sample_rate"])
        channels = int(s["channels"])
        bitrate = int(s.get("bit_rate") or 0)
    except (KeyError, ValueError, TypeError) as exc:
        raise ImportFailure(f"Invalid audio metadata {relative!r}: {exc}") from exc
    if not 500 <= length <= 24 * 3600 * 1000 or not 8000 <= rate <= 192000 or channels not in (1, 2):
        raise ImportFailure(f"Invalid duration, sample rate or channel count: {relative!r}")
    tags = {str(k).lower(): str(v).strip() for k, v in data["format"].get("tags", {}).items()}
    fallback = src.stem.replace("_", " ").strip()
    return Track(relative, (tags.get("title") or fallback)[:255],
                 (tags.get("artist") or "Unknown Artist")[:255],
                 (tags.get("album") or "Unknown Album")[:255],
                 length, rate, channels, bitrate,
                 {".mp3": 3, ".ogg": 5, ".wav": (7 if codec == "pcm_s24le" else 0)}[ext])


def references(refs: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    if not refs.exists():
        return result
    if refs.is_symlink() or not refs.is_dir():
        raise ImportFailure(f"Invalid reference directory: {refs}")
    for file in refs.iterdir():
        match = CUT_RE.fullmatch(file.name)
        if match is None:
            continue
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 4096:
            raise ImportFailure(f"Unsafe reference: {file}")
        raw = file.read_bytes()
        if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise ImportFailure(f"Malformed reference: {file}")
        rel = raw[:-1].decode("utf-8", errors="strict")
        if rel in result:
            raise ImportFailure(f"Duplicate reference to {rel!r}")
        result[rel] = int(match.group(1))
    return result


def write_reference(refs: Path, cut: str, relative: str) -> Path:
    refs.mkdir(mode=0o750, parents=True, exist_ok=True)
    if refs.is_symlink():
        raise ImportFailure("References directory is a symlink")
    dest = refs / (cut + ".ref")
    if dest.exists() or dest.is_symlink():
        raise ImportFailure(f"Reference already exists: {dest}")
    if len(relative.encode()) + 1 > 4096 or INVALID.search(relative):
        raise ImportFailure("Reference path too long or contains control characters")
    # The reference directory is normally root:rivendell (0750). Reference
    # files must inherit that group, or CAE running as rivendell cannot read
    # the path despite a valid cart record and readable original NAS file.
    parent = refs.stat()
    fd, tmp = tempfile.mkstemp(prefix=".rdexternal-", dir=refs)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchown(output.fileno(), -1, parent.st_gid)
            os.fchmod(output.fileno(), 0o640)
            output.write(relative.encode("utf-8") + b"\n")
            output.flush()
            os.fsync(output.fileno())
        # Refuse concurrent insertion: no overwrites (atomic hard link).
        linked = False
        try:
            os.link(tmp, dest, follow_symlinks=False)
            linked = True
            os.unlink(tmp)
            dirfd = os.open(refs, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except Exception:
            if linked:
                dest.unlink(missing_ok=True)
            raise
        return dest
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_db_settings(path: Path) -> dict:
    parser = configparser.RawConfigParser()
    if not parser.read(path):
        raise ImportFailure(f"Cannot read Rivendell config: {path}")
    section = parser["mySQL"]
    return {
        "host": section.get("Hostname", "localhost"),
        "user": section.get("Loginname", "rduser"),
        "password": section.get("Password", ""),
        "database": section.get("Database", "Rivendell"),
        "charset": "utf8mb4",
        "connect_timeout": 10,
        "autocommit": False,
    }


def check_db(conn, group: str, first: int, last: int) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT NAME FROM GROUPS WHERE NAME=%s", (group,))
        if cur.fetchone() is None:
            raise ImportFailure(f"Group {group!r} must first be created in RDAdmin")
        cur.execute("SELECT NUMBER FROM CART WHERE NUMBER BETWEEN %s AND %s",
                    (first, last))
        return {int(row[0]) for row in cur.fetchall()}


def existing_db_cart(conn, cart: int, group: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT GROUP_NAME, TYPE FROM CART WHERE NUMBER=%s", (cart,))
        row = cur.fetchone()
        if row is None:
            return False
        if row[0].strip() != group or int(row[1]) != 1:
            raise ImportFailure(f"Cart {cart} is not a {group} audio cart")
        cur.execute("SELECT CUT_NAME FROM CUTS WHERE CUT_NAME=%s",
                    (f"{cart:06d}_001",))
        return cur.fetchone() is not None


def insert_cart(conn, cart: int, group: str, track: Track) -> None:
    cut = f"{cart:06d}_001"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO CART "
            "(NUMBER,TYPE,GROUP_NAME,TITLE,ARTIST,ALBUM,AVERAGE_LENGTH,"
            "AVERAGE_SEGUE_LENGTH,CUT_QUANTITY,VALIDITY) "
            "VALUES (%s,1,%s,%s,%s,%s,%s,%s,1,2)",
            (cart, group, track.title, track.artist, track.album,
             track.length_ms, track.length_ms))
        try:
            cur.execute(
                "INSERT INTO CUTS "
                "(CUT_NAME,CART_NUMBER,DESCRIPTION,LENGTH,ORIGIN_DATETIME,"
                "CODING_FORMAT,SAMPLE_RATE,BIT_RATE,CHANNELS,START_POINT,"
                "END_POINT,SEGUE_START_POINT,SEGUE_END_POINT,VALIDITY) "
                "VALUES (%s,%s,%s,%s,NOW(),%s,%s,%s,%s,0,%s,0,%s,2)",
                (cut, cart, track.title[:64], track.length_ms, track.coding,
                 track.sample_rate, track.bitrate, track.channels,
                 track.length_ms, track.length_ms))
        except Exception:
            # Important for upstream MyISAM installs: a CUTS insertion may fail
            # after CART insertion has already become persistent.
            cur.execute("DELETE FROM CART WHERE NUMBER=%s", (cart,))
            conn.commit()
            raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True, help="Existing NAS music directory")
    ap.add_argument("--refs", type=Path, default=Path("/var/lib/rivendell/external-media"),
                    help="Local SSD reference directory (not on NAS)")
    ap.add_argument("--group", required=True, help="Existing Rivendell audio group (<=10 chars)")
    ap.add_argument("--first-cart", type=int, default=100000)
    ap.add_argument("--last-cart", type=int, default=899999)
    ap.add_argument("--limit", type=int, default=None, help="First N tracks, for test imports")
    ap.add_argument("--config", type=Path, default=Path("/etc/rd.conf"))
    ap.add_argument("--reference-prefix", default="",
                    help="Named NAS source ID. Stored references are ID/relative-path")
    ap.add_argument("--commit", action="store_true", help="Write CART/CUTS rows and refs")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,10}", args.group):
        ap.error("Group must contain 1-10 letters, digits, underscores or hyphens")
    if not 1 <= args.first_cart <= args.last_cart <= CART_MAX:
        ap.error("Invalid cart number range")
    if args.limit is not None and args.limit < 1:
        ap.error("--limit must be positive")
    if args.reference_prefix and (
        len(args.reference_prefix) > 1024
        or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}(?:/[A-Za-z0-9_ .-]+)*",
                            args.reference_prefix)
        or any(part in ("", ".", "..") for part in args.reference_prefix.split("/"))
    ):
        ap.error("Invalid NAS source reference prefix")
    root = args.root.resolve(strict=True)
    if not root.is_dir() or root == Path("/"):
        ap.error("--root must be an existing NAS subdirectory")
    refs = args.refs.absolute()
    if refs == root or refs.is_relative_to(root):
        ap.error("--refs must be on local storage, outside the music directory")
    if shutil.which("ffprobe") is None:
        raise ImportFailure("ffprobe is not installed")
    if args.commit and not (os.statvfs(root).f_flag & os.ST_RDONLY):
        raise ImportFailure("Refusing commit: mount the music filesystem READ-ONLY")
    previous = references(refs)
    tracks = []
    skipped = 0
    for relative in scan_paths(root, args.limit):
        reference = f"{args.reference_prefix}/{relative}" if args.reference_prefix else relative
        if reference in previous:
            continue
        try:
            tracks.append(probe(root, relative))
        except (ImportFailure, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            skipped += 1
            print(f"SKIP {relative!r}: {exc}", file=sys.stderr)
    print(f"SCAN new={len(tracks)} previously_indexed={len(previous)} rejected={skipped}")
    if not args.commit:
        print("DRY RUN: no media files, references, or database records changed.")
        for track in tracks[:10]:
            print(f"  {track.relative}: {track.artist} / {track.title} ({track.length_ms} ms)")
        return 0 if skipped == 0 else 2
    if skipped:
        raise ImportFailure("Refusing partial commit after unsupported/corrupt files; fix or remove them from scan")
    try:
        import pymysql
    except ImportError as exc:
        raise ImportFailure("Install python3-pymysql before --commit") from exc
    conn = pymysql.connect(**read_db_settings(args.config))
    inserted = 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK('rivendell_complete_external_index',15)")
            if cur.fetchone()[0] != 1:
                raise ImportFailure("Could not acquire catalog import lock")
        used = check_db(conn, args.group, args.first_cart, args.last_cart)
        for rel, cart in previous.items():
            if args.reference_prefix and not rel.startswith(args.reference_prefix + "/"):
                # Other independent NAS sources may use different Rivendell
                # groups, and must not be interpreted as a group mismatch.
                continue
            if not existing_db_cart(conn, cart, args.group):
                raise ImportFailure(f"Orphan reference {cart:06d}_001.ref: repair manually before import")
        next_cart = args.first_cart
        for track in tracks:
            while next_cart in used:
                next_cart += 1
            if next_cart > args.last_cart:
                raise ImportFailure("Ran out of cart numbers")
            cut = f"{next_cart:06d}_001"
            ref_path = None
            db_inserted = False
            try:
                insert_cart(conn, next_cart, args.group, track)
                db_inserted = True
                reference = (f"{args.reference_prefix}/{track.relative}"
                             if args.reference_prefix else track.relative)
                ref_path = write_reference(refs, cut, reference)
                conn.commit()
            except Exception:
                conn.rollback()
                # Rivendell defaults to MyISAM, so clean up any partially
                # inserted records explicitly. Do not touch pre-existing carts.
                if db_inserted:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM CUTS WHERE CUT_NAME=%s", (cut,))
                        cur.execute("DELETE FROM CART WHERE NUMBER=%s", (next_cart,))
                    conn.commit()
                if ref_path is not None and ref_path.exists():
                    ref_path.unlink()
                raise
            used.add(next_cart)
            inserted += 1
            if inserted % 100 == 0:
                print(f"Indexed {inserted}/{len(tracks)}", flush=True)
        print(f"COMMITTED {inserted} new carts, no original audio files changed.")
        return 0
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT RELEASE_LOCK('rivendell_complete_external_index')")
        finally:
            conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ImportFailure, OSError, subprocess.SubprocessError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
