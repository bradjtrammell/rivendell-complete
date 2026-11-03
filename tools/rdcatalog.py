#!/usr/bin/env python3
"""Export playable Rivendell CART rows for rdsmartclock, excluding missing NAS audio."""
from __future__ import annotations

import argparse
import configparser
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from rdexternal import media_path, read_db_settings


class CatalogError(RuntimeError):
    pass


def load_external_map(config_path: Path) -> tuple[Path | None, dict[int, str]]:
    cfg = configparser.RawConfigParser()
    if not cfg.read(config_path):
        raise CatalogError(f"Cannot read {config_path}")
    if not cfg.has_section("ExternalAudio"):
        return None, {}
    root_s = cfg.get("ExternalAudio", "Root", fallback="").strip()
    refs_s = cfg.get("ExternalAudio", "References", fallback="").strip()
    if not root_s and not refs_s:
        return None, {}
    if not root_s or not refs_s:
        raise CatalogError("Both ExternalAudio Root and References are required")
    root, refs = Path(root_s).resolve(strict=True), Path(refs_s).resolve(strict=True)
    if not root.is_dir() or not refs.is_dir():
        raise CatalogError("External NAS library or refs directory inaccessible")
    mappings: dict[int, str] = {}
    for file in refs.iterdir():
        if not re.fullmatch(r"[0-9]{6}_001\.ref", file.name):
            continue
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 4096:
            raise CatalogError(f"Unsafe reference: {file}")
        data = file.read_bytes()
        if data.count(b"\n") != 1 or not data.endswith(b"\n"):
            raise CatalogError(f"Malformed reference: {file}")
        rel = data[:-1].decode("utf-8", errors="strict")
        mappings[int(file.name[:6])] = rel
    return root, mappings


def export_catalog(config_path: Path, groups: list[str]) -> list[dict]:
    import pymysql
    if not groups or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,9}", g) for g in groups):
        raise CatalogError("Supply one or more valid 1-10-character music groups")
    root, mappings = load_external_map(config_path)
    conn = pymysql.connect(**read_db_settings(config_path))
    try:
        with conn.cursor() as cur:
            binds = ",".join("%s" for _ in groups)
            cur.execute(
                "SELECT C.NUMBER,C.GROUP_NAME,C.TITLE,C.ARTIST,C.ALBUM,"
                "C.AVERAGE_LENGTH,C.VALIDITY "
                "FROM CART C WHERE C.TYPE=1 AND C.GROUP_NAME IN ("+binds+") "
                "AND C.AVERAGE_LENGTH BETWEEN 500 AND 900000 "
                "AND C.VALIDITY IN (2,3) ORDER BY C.NUMBER", tuple(groups))
            rows = cur.fetchall()
    finally:
        conn.close()
    result = []
    for cart, group, title, artist, album, length, validity in rows:
        cart = int(cart)
        # CAE plays /var/snd WAV cuts; NAS .ref files only store provenance.
        native_cut = Path("/var/snd") / f"{cart:06d}_001.wav"
        if native_cut.is_symlink() or not native_cut.is_file() or native_cut.stat().st_size == 0:
            print(f"SKIP cart {cart}: native playable audio missing", file=sys.stderr)
            continue
        if root is not None:
            ref = mappings.get(cart)
            if ref:
                try:
                    src = media_path(root, ref)
                    if src.suffix.lower() not in (".mp3",".wav",".ogg"):
                        continue
                except (OSError, ValueError, RuntimeError) as exc:
                    print(f"SKIP unavailable NAS cart {cart}: {exc}",file=sys.stderr)
                    continue
            else:
                # External library mode: include managed carts only if /var/snd
                # contains actual media; do not schedule ghost cart records.
                if not (Path("/var/snd")/f"{cart:06d}_001.wav").is_file():
                    continue
        result.append({
            "cart": cart,"group":str(group).strip(),
            "title":str(title or "").strip(),
            "artist":str(artist or "Unknown Artist").strip(),
            "album":str(album or "Unknown Album").strip(),
            "length_ms":int(length),
        })
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config",type=Path,default=Path("/etc/rd.conf"))
    ap.add_argument("--group",action="append",required=True,help="Music group (repeatable)")
    ap.add_argument("--output",type=Path,help="Atomic JSON export file; default stdout")
    args = ap.parse_args(argv)
    data = export_catalog(args.config,args.group)
    if not data:
        raise CatalogError("No playable music rows for requested group(s)")
    payload=(json.dumps(data,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    if args.output is None:
        sys.stdout.buffer.write(payload)
        return 0
    dest=args.output.expanduser().absolute()
    if dest.exists() or dest.is_symlink():
        raise CatalogError("Output exists; refusing to overwrite existing catalog")
    dest.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".catalog-",dir=dest.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            os.fchmod(f.fileno(),0o640)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp,dest,follow_symlinks=False)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print(f"Exported {len(data)} playable music carts to {dest}",file=sys.stderr)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (CatalogError,OSError,ValueError,UnicodeError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        raise SystemExit(1)
