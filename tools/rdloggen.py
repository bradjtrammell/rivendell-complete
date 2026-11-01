#!/usr/bin/env python3
"""Protected recurring Rivendell daily log generator."""
from __future__ import annotations
import argparse
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

class LogError(RuntimeError):
    pass

def command(service: str, offset: int) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,10}", service):
        raise LogError("Invalid service name (1-10 letters, digits, _ or -)")
    if not 0 <= offset <= 30:
        raise LogError("Day offset out of bounds")
    return ["rdlogmanager", "-P", "-g", "-s", service, "-d", str(offset)]

def generate(service: str, days: int, dry_run: bool, lock_dir: Path) -> int:
    if not 1 <= days <= 31:
        raise LogError("Days must be 1-31")
    if shutil.which("rdlogmanager") is None and not dry_run:
        raise LogError("rdlogmanager not installed")
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if lock_dir.is_symlink() or lock_dir.stat().st_uid != os.getuid() or lock_dir.stat().st_mode & 0o077:
        raise LogError("Lock directory must be owned by this user with 0700 permissions")
    fd = os.open(lock_dir / "generate.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LogError("Another generator already holds the lock") from exc
        failed = []
        for day in range(days):
            args = command(service, day)
            if dry_run:
                print("DRY RUN:", " ".join(args))
                continue
            result = subprocess.run(args, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=120,
                                    check=False)
            print(f"day={day} result={result.returncode}", flush=True)
            if result.stdout.strip():
                print(result.stdout[-4000:])
            if result.stderr.strip():
                print(result.stderr[-4000:], file=sys.stderr)
            if result.returncode:
                failed.append(day)
        if failed:
            raise LogError(f"Failed day offsets: {failed}")
        return 0
    finally:
        os.close(fd)

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--service", required=True, help="Existing RDLogManager service")
    p.add_argument("--days", type=int, default=7, help="Future days starting tomorrow")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--lock-dir", type=Path, default=Path.home()/".local/state/rivendell-complete")
    args = p.parse_args(argv)
    return generate(args.service, args.days, args.dry_run, args.lock_dir)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (LogError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
