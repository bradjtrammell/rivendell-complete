#!/usr/bin/env python3
"""Read-only inventory of configured Rivendell Complete NAS mounts.

The same fixed named-mount contract is used by the privileged helper, library
importer and Qt Control Center. Listing never needs elevated privileges.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path("/mnt/radio-music")
NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
REMOTE_NFS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*:/[A-Za-z0-9_./-]+\Z")
REMOTE_SMB = re.compile(r"//[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_./-]+\Z")


class MountError(ValueError):
    pass


def mount_path(name: str) -> Path:
    if not isinstance(name, str) or NAME.fullmatch(name) is None or name == "legacy":
        raise MountError("Source name must be 1-32 lowercase letters, numbers, - or _, starting with a letter")
    return ROOT / name


def validate_source(protocol: str, source: str) -> None:
    expression = {"nfs": REMOTE_NFS, "smb": REMOTE_SMB}.get(protocol)
    if expression is None or not isinstance(source, str) or expression.fullmatch(source) is None:
        raise MountError("Invalid NFS export or SMB share")


def fstab_mounts(fstab: Path = Path("/etc/fstab"), root: Path = ROOT) -> list[dict]:
    """Only accept exact, directly nested mounts. Never parse arbitrary paths."""
    result = []
    entries: set[str] = set()
    for line in fstab.read_text(encoding="utf-8").splitlines():
        data = line.split()
        if len(data) != 6 or data[0].startswith("#"):
            continue
        source, target, fstype, options, dump, passno = data
        if fstype not in ("nfs", "nfs4", "cifs"):
            continue
        if target == str(root):
            name = "legacy"
        elif target.startswith(str(root) + "/"):
            name = target[len(str(root)) + 1:]
            if NAME.fullmatch(name) is None or name == "legacy":
                continue
        else:
            continue
        if name in entries:
            raise MountError("Duplicate NAS mount entry: " + name)
        entries.add(name)
        result.append({
            "name": name,
            "source": source,
            "protocol": "SMB" if fstype == "cifs" else "NFS",
            "path": target,
            "readonly_configured": "ro" in options.split(","),
            "legacy": name == "legacy",
        })
    return sorted(result, key=lambda entry: (entry["legacy"], entry["name"]))


def mounted_details(path: Path, *, timeout: int = 5) -> tuple[str, str, bool]:
    try:
        out = subprocess.run(
            ["/usr/bin/findmnt", "-rn", "-M", str(path),
             "-o", "SOURCE,FSTYPE,OPTIONS"],
            stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", "", False
    parts = out.stdout.strip().split(None, 2)
    if out.returncode or len(parts) != 3:
        return "", "", False
    return parts[0], parts[1], "ro" in parts[2].split(",")


def mount_inventory(fstab: Path = Path("/etc/fstab"), root: Path = ROOT,
                    *, probe: bool = True) -> list[dict]:
    items = fstab_mounts(fstab, root)
    for item in items:
        item["mounted"] = False
        item["readonly"] = False
        if probe:
            # systemd may have mounted only its autofs trigger following boot.
            # A bounded stat wakes the real NFS/CIFS mount before findmnt.
            # Never write to the source or follow symlinks in the collection.
            if item["readonly_configured"]:
                try:
                    subprocess.run(
                        ["/usr/bin/stat", "--", item["path"] + "/."],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=5, check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
            source, fstype, read_only = mounted_details(Path(item["path"]))
            item["mounted"] = (
                source == item["source"]
                and fstype in (("cifs",) if item["protocol"] == "SMB" else ("nfs", "nfs4"))
            )
            item["readonly"] = item["mounted"] and read_only
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable source inventory")
    args = parser.parse_args(argv)
    items = mount_inventory()
    if args.json:
        print(json.dumps(items, indent=2))
    else:
        for item in items:
            status = "read-only" if item["readonly"] else "offline or unsafe"
            print(f'{item["name"]:32} {item["protocol"]:3} {item["path"]}  {status}')
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (MountError, OSError, UnicodeError) as exc:
        parser = __import__("sys")
        print(f"ERROR: {exc}", file=parser.stderr)
        raise SystemExit(1)
