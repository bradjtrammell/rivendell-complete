#!/usr/bin/python3
"""Read-only, full-library diagnostic for direct-from-NAS Rivendell cuts.

No audio file, reference, mount or database row is created or modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rdexternal import ImportFailure, media_path, read_db_settings, references
from rdmounts import mount_inventory, MountError

ROOT = Path("/mnt/radio-music")
REFS = Path("/var/lib/rivendell/external-media")


class DiagnosticError(RuntimeError):
    pass


def diagnose(*, root: Path = ROOT, refs: Path = REFS,
             config: Path = Path("/etc/rd.conf")) -> dict:
    import configparser
    cfg = configparser.RawConfigParser()
    if not cfg.read(config):
        raise DiagnosticError("Cannot read /etc/rd.conf")
    expected = (cfg.get("ExternalAudio", "Root", fallback=""),
                cfg.get("ExternalAudio", "References", fallback=""))
    if expected != (str(root), str(refs)):
        raise DiagnosticError(
            "Native CAE direct-audio configuration is missing or mismatched")
    inventory = mount_inventory()
    if not inventory:
        raise DiagnosticError("No persistent NAS mounts found in /etc/fstab")
    offline = [item["name"] for item in inventory
               if not item["mounted"] or not item["readonly"]]
    report = {
        "configured_mounts": len(inventory),
        "offline_or_writable_mounts": offline,
        "referenced_carts": 0,
        "available_originals": 0,
        "missing_originals": 0,
        "missing_cart_rows": 0,
        "missing_cut_rows": 0,
        "invalid_cut_metadata": 0,
        "examples": [],
    }
    if offline:
        report["status"] = "blocked_nas_offline"
        return report
    if root.is_symlink() or refs.is_symlink() or not refs.is_dir():
        raise DiagnosticError("NAS root/reference directory unavailable or unsafe")
    mapped = references(refs)
    report["referenced_carts"] = len(mapped)
    if not mapped:
        report["status"] = "no_imported_references"
        return report
    import pymysql
    db = pymysql.connect(**read_db_settings(config))
    try:
        rows = {}
        ids = sorted(mapped.values())
        for start in range(0, len(ids), 300):
            segment = ids[start:start + 300]
            with db.cursor() as cur:
                cur.execute(
                    "SELECT C.NUMBER,C.TYPE,C.CUT_QUANTITY,C.VALIDITY,"
                    "T.CUT_NAME,T.CART_NUMBER,T.LENGTH,T.VALIDITY "
                    "FROM CART C LEFT JOIN CUTS T ON T.CUT_NAME="
                    "CONCAT(LPAD(C.NUMBER,6,'0'),'_001') "
                    "WHERE C.NUMBER IN (" + ",".join(["%s"] * len(segment)) + ")",
                    tuple(segment))
                for row in cur.fetchall():
                    rows[int(row[0])] = row
        for relative, cart in sorted(mapped.items(), key=lambda t: t[1]):
            problems = []
            try:
                original = media_path(root, relative)
                if original.suffix.lower() not in (".mp3", ".ogg", ".wav"):
                    problems.append("unsupported_audio_type")
                elif original.stat().st_size == 0:
                    problems.append("empty_original")
                else:
                    report["available_originals"] += 1
            except (OSError, ValueError, RuntimeError, ImportFailure):
                problems.append("original_unavailable")
            if any(p in problems for p in ("original_unavailable", "empty_original",
                                           "unsupported_audio_type")):
                report["missing_originals"] += 1
            row = rows.get(cart)
            if row is None:
                report["missing_cart_rows"] += 1
                problems.append("cart_missing")
            else:
                if row[4] is None or int(row[5] or 0) != cart:
                    report["missing_cut_rows"] += 1
                    problems.append("cut_missing")
                elif (int(row[1]) != 1 or int(row[2] or 0) != 1
                      or int(row[3] or 0) not in (2, 3)
                      or int(row[6] or 0) <= 0
                      or int(row[7] or 0) not in (2, 3)):
                    report["invalid_cut_metadata"] += 1
                    problems.append("invalid_metadata")
            if problems and len(report["examples"]) < 25:
                report["examples"].append({
                    "cart": cart, "source": relative, "problems": problems})
    finally:
        db.close()
    report["status"] = ("ready_for_native_playback_test" if
                        report["available_originals"] == report["referenced_carts"]
                        and report["missing_cart_rows"] == 0
                        and report["missing_cut_rows"] == 0
                        and report["invalid_cut_metadata"] == 0
                        else "repair_required")
    report["runtime_playback_verified"] = False
    report["note"] = ("Checks catalog/reference/original availability; "
                      "only an actual CAE/RDAirPlay playback test proves decoding.")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if os.geteuid() != 0:
        raise DiagnosticError("Run as root for catalog and restricted NAS references")
    report = diagnose()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "ready_for_native_playback_test" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DiagnosticError, ImportFailure, MountError,
            OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
