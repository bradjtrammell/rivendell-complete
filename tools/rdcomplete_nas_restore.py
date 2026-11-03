#!/usr/bin/python3
"""Recover read-only NFS/SMB station sources after network/boot transitions.

Reads configured fstab entries without rewriting them; only touches exact
/mnt/radio-music/<name> paths. A systemd timer retries failed remote mounts
without restarting Rivendell or modifying the audio catalog.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys

sys.path.insert(0, "/usr/local/libexec/rivendell-complete")
from rdmounts import (ROOT, MountError, fstab_mounts, mount_inventory)


class RestoreError(RuntimeError):
    pass


def check_target(path: Path, root: Path = ROOT) -> None:
    if root.is_symlink() or path.is_symlink():
        raise RestoreError("NAS mount root/target is a symlink")
    if not path.is_relative_to(root):
        raise RestoreError("Mount target outside the NAS root")
    if not path.is_dir():
        raise RestoreError("NAS mountpoint does not exist; refusing to create a replacement")


def run(command: list[str], timeout: int) -> bool:
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=timeout, check=False)
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def refresh(fstab: Path = Path("/etc/fstab"), root: Path = ROOT) -> tuple[int, int]:
    entries = fstab_mounts(fstab, root)
    if not entries:
        print("No configured NAS source found in /etc/fstab; nothing to recover.")
        return 0, 0
    if len(entries) > 64:
        raise RestoreError("More than 64 NAS sources registered; refusing unbounded recovery")
    ok = 0
    failures = 0
    for entry in entries:
        name = entry["name"]
        try:
            if not entry["readonly_configured"]:
                raise RestoreError("Source fstab entry is not read-only")
            target = Path(entry["path"])
            check_target(target, root)
            # Start the generator's automount if present, then trigger its
            # backing mount. A failed network service is retried by timer.
            if "x-systemd.automount" in _mount_options(fstab, entry["path"]):
                escaped = subprocess.run(
                    ["/usr/bin/systemd-escape", "--path", "--suffix=automount", str(target)],
                    capture_output=True, text=True, timeout=5, check=False)
                if escaped.returncode == 0:
                    unit = escaped.stdout.strip()
                    if unit.endswith(".automount"):
                        run(["/usr/bin/systemctl", "start", unit], timeout=15)
            run(["/usr/bin/timeout", "-k", "2", "16",
                 "/usr/bin/stat", "--", str(target / ".")], timeout=20)
            live = mount_inventory(fstab, root, probe=False)
            row = next((i for i in live if i["path"] == entry["path"]), None)
            if row is None:
                raise RestoreError("Mount disappeared from configuration")
            actual = subprocess.run(
                ["/usr/bin/findmnt", "-rn", "-M", str(target),
                 "-o", "SOURCE,FSTYPE,OPTIONS"],
                capture_output=True, text=True, timeout=5, check=False)
            fields = actual.stdout.strip().split(None, 2)
            if actual.returncode or len(fields) != 3:
                raise RestoreError("NAS mount offline")
            if fields[0] != entry["source"]:
                raise RestoreError("Mounted source does not match persistent configuration")
            if fields[1] not in (("cifs",) if entry["protocol"] == "SMB" else ("nfs", "nfs4")):
                raise RestoreError("Unexpected filesystem type at source")
            if "ro" not in fields[2].split(","):
                raise RestoreError("Recovered NAS mount is writable")
            ok += 1
            print(f"ONLINE read-only: {name} ({entry['protocol']}) -> {entry['path']}")
        except (OSError, RestoreError, subprocess.TimeoutExpired) as exc:
            failures += 1
            print(f"OFFLINE {name}: {exc}", file=sys.stderr)
    return ok, failures


def _mount_options(fstab: Path, target: str) -> set[str]:
    for line in fstab.read_text(encoding="utf-8").splitlines():
        words = line.split()
        if len(words) == 6 and words[1] == target:
            return set(words[3].split(","))
    return set()


def main() -> int:
    if os.geteuid() != 0:
        raise RestoreError("NAS recovery must run as root through systemd")
    os.umask(0o077)
    ok, failed = refresh()
    print(f"NAS restore verification: online={ok}, offline={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RestoreError, MountError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
