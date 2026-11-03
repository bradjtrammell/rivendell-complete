#!/usr/bin/python3
"""Audit existing NAS-linked carts; repair only proven importer metadata defects.

No cart or original audio is ever deleted, moved or re-imported. Repairs require
root, stop RDAirPlay, verify original NAS audio read-only, create a private
recovery snapshot, then update only matching importer-created CART/CUTS rows.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from rdexternal import media_path, probe, read_db_settings, references, ImportFailure
from rdmounts import fstab_mounts, mount_inventory

REFS = Path("/var/lib/rivendell/external-media")
ROOT = Path("/mnt/radio-music")
BACKUPS = Path("/var/lib/rivendell-complete/catalog-audit")
CUT_NAME = re.compile(r"[0-9]{6}_001\Z")


class AuditError(RuntimeError):
    pass


def classify(cart: int, row: dict | None) -> list[str]:
    if row is None:
        return ["cart_missing"]
    problems = []
    if int(row["type"]) != 1:
        return ["cart_not_audio"]
    if row["cut_name"] is None or row["cut_cart"] is None:
        return ["cut_missing"]
    if int(row["cut_cart"]) != cart:
        problems.append("cut_cart_mismatch")
    if int(row["length"] or 0) <= 0:
        problems.append("zero_length_cut")
    if int(row["quantity"] or 0) != 1:
        problems.append("incorrect_cut_quantity")
    if int(row["cart_validity"] or 0) == 0:
        problems.append("invalid_cart_flag")
    if int(row["cut_validity"] or 0) == 0:
        problems.append("invalid_cut_flag")
    days = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
    if all(row.get(d) != "Y" for d in days):
        problems.append("no_enabled_days")
    return problems


def create_recovery_copy(records: list[dict], folder: Path = BACKUPS) -> Path:
    if folder.is_symlink():
        raise AuditError("Recovery folder must not be a symlink")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.stat().st_uid != os.geteuid() or folder.stat().st_mode & 0o077:
        raise AuditError("Recovery directory has unsafe owner/permissions")
    name = datetime.now(timezone.utc).strftime("import-carts-%Y%m%dT%H%M%S%fZ-") + str(os.getpid()) + ".json"
    target = folder / name
    with target.open("x", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(records, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target


def verify_nas_sources() -> None:
    entries = mount_inventory()
    if not entries:
        raise AuditError("No persistent NAS source is registered; do not repair empty mounts")
    if any(not item["readonly"] or not item["mounted"] for item in entries):
        offline = [str(item["name"]) for item in entries if not item["readonly"]]
        raise AuditError("NAS offline or writable: " + ", ".join(offline))


def audit(commit: bool = False, *, root: Path = ROOT, refs: Path = REFS) -> dict:
    import pymysql
    if os.geteuid() != 0:
        raise AuditError("This tool requires root for protected Rivendell DB and references")
    if commit:
        import subprocess
        if subprocess.run(["/usr/bin/pgrep", "-x", "rdairplay"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          check=False).returncode == 0:
            raise AuditError("Close RDAirPlay before repairing existing import metadata")
    verify_nas_sources()
    if not root.is_dir() or root.is_symlink() or refs.is_symlink() or not refs.is_dir():
        raise AuditError("NAS root or reference store missing/unsafe")
    paths = references(refs)
    if not paths:
        raise AuditError("No NAS reference carts found: no changes made")
    media: dict[int, tuple[str, Path]] = {}
    missing = []
    for relative, cart in paths.items():
        try:
            source = media_path(root, relative)
            if source.suffix.lower() not in (".mp3", ".ogg", ".wav"):
                raise AuditError("Unsupported original audio encoding")
            media[cart] = (relative, source)
        except (OSError, ValueError, RuntimeError, ImportFailure) as exc:
            missing.append({"cart": cart, "relative": relative,
                            "reason": str(exc)[:240]})
    if missing:
        raise AuditError(
            f"{len(missing)} original NAS files are unavailable; "
            f"first example: cart {missing[0]['cart']}. "
            "Repair requires the original shares online, not a new import")
    conn = pymysql.connect(**read_db_settings(Path("/etc/rd.conf")))
    rows: dict[int, dict | None] = {}
    columns = [
        "number", "type", "quantity", "cart_validity", "group",
        "cut_name", "cut_cart", "length", "cut_validity",
        "sun", "mon", "tue", "wed", "thu", "fri", "sat",
    ]
    try:
        carts = sorted(media)
        for start in range(0, len(carts), 300):
            segment = carts[start:start+300]
            placeholders = ",".join(["%s"] * len(segment))
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT C.NUMBER,C.TYPE,C.CUT_QUANTITY,C.VALIDITY,C.GROUP_NAME,"
                    "T.CUT_NAME,T.CART_NUMBER,T.LENGTH,T.VALIDITY,"
                    "T.SUN,T.MON,T.TUE,T.WED,T.THU,T.FRI,T.SAT "
                    "FROM CART C LEFT JOIN CUTS T ON T.CUT_NAME="
                    "CONCAT(LPAD(C.NUMBER,6,'0'),'_001') "
                    "WHERE C.NUMBER IN (" + placeholders + ")", tuple(segment))
                for row in cur.fetchall():
                    converted = dict(zip(columns, row))
                    rows[int(row[0])] = converted
        affected = []
        for cart, (relative, _) in media.items():
            problems = classify(cart, rows.get(cart))
            if problems:
                affected.append({"cart": cart, "relative": relative,
                                 "problems": problems, "before": rows.get(cart)})
        summary = {
            "linked_carts": len(media), "playable_metadata": len(media) - len(affected),
            "needs_repair": len(affected),
            "examples": [{"cart": x["cart"], "issues": x["problems"]}
                         for x in affected[:15]],
        }
        if not commit:
            return summary
        # Only importer metadata, for safely resolved tracks; no cart deletion.
        unsupported = {"cart_missing", "cart_not_audio", "cut_cart_mismatch"}
        if any(unsupported.intersection(item["problems"]) for item in affected):
            raise AuditError("Ambiguous/missing CART records; no bulk repair permitted")
        if not affected:
            summary["updated"] = 0
            return summary
        backup = create_recovery_copy(affected)
        summary["recovery_file"] = str(backup)
        updated = 0
        for item in affected:
            cart = item["cart"]
            issues = item["problems"]
            relative, _ = media[cart]
            track = probe(root, relative)
            with conn.cursor() as cur:
                cut = f"{cart:06d}_001"
                if "cut_missing" in issues:
                    cur.execute(
                        "INSERT INTO CUTS "
                        "(CUT_NAME,CART_NUMBER,DESCRIPTION,LENGTH,ORIGIN_DATETIME,"
                        "CODING_FORMAT,SAMPLE_RATE,BIT_RATE,CHANNELS,START_POINT,"
                        "END_POINT,SEGUE_START_POINT,SEGUE_END_POINT,VALIDITY)"
                        "VALUES (%s,%s,%s,%s,NOW(),%s,%s,%s,%s,0,%s,0,%s,2)",
                        (cut, cart, track.title[:64], track.length_ms,
                         track.coding, track.sample_rate, track.bitrate,
                         track.channels, track.length_ms, track.length_ms))
                if "zero_length_cut" in issues:
                    cur.execute("UPDATE CUTS SET LENGTH=%s,END_POINT=%s,"
                                "SEGUE_END_POINT=%s WHERE CUT_NAME=%s AND CART_NUMBER=%s",
                                (track.length_ms, track.length_ms, track.length_ms, cut, cart))
                if "invalid_cut_flag" in issues:
                    cur.execute("UPDATE CUTS SET VALIDITY=2 WHERE CUT_NAME=%s AND CART_NUMBER=%s",
                                (cut, cart))
                if "no_enabled_days" in issues:
                    cur.execute(
                        "UPDATE CUTS SET SUN='Y',MON='Y',TUE='Y',WED='Y',"
                        "THU='Y',FRI='Y',SAT='Y' WHERE CUT_NAME=%s AND CART_NUMBER=%s",
                        (cut, cart))
                if "incorrect_cut_quantity" in issues or "invalid_cart_flag" in issues:
                    cur.execute("UPDATE CART SET CUT_QUANTITY=1,VALIDITY=2,"
                                "AVERAGE_LENGTH=GREATEST(AVERAGE_LENGTH,%s) "
                                "WHERE NUMBER=%s AND TYPE=1", (track.length_ms, cart))
            conn.commit()
            updated += 1
        summary["updated"] = updated
        return summary
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair", action="store_true",
                        help="Repair only positively identified metadata defects after backup")
    args = parser.parse_args()
    print(json.dumps(audit(commit=args.repair), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuditError, ImportFailure, OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
