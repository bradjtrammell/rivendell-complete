#!/usr/bin/python3
"""Browse mounted NAS folders without root privileges, writes, or symlink escapes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
# The installed entrypoint is in /usr/local/bin; shared mount code is
# installed under the root-owned libexec directory.
sys.path.insert(0, "/usr/local/libexec/rivendell-complete")
import stat
import sys

from rdmounts import ROOT, mount_inventory, MountError


class FolderError(ValueError):
    pass


def resolve_folder(name: str, folder: str, *, inventory: list[dict],
                   root: Path = ROOT) -> Path:
    matches = [item for item in inventory if item["name"] == name]
    if len(matches) != 1 or not matches[0]["readonly"] or not matches[0]["mounted"]:
        raise FolderError("Select a mounted, read-only NAS source")
    source = root if matches[0]["legacy"] else root / name
    if source.is_symlink():
        raise FolderError("Source mount is a symlink")
    parent = source.resolve(strict=True)
    if not folder:
        return source
    if not isinstance(folder, str) or len(folder) > 1024 or folder.startswith("/") or "\\" in folder:
        raise FolderError("Invalid folder selection")
    candidate = source
    for segment in folder.split("/"):
        if not segment or segment in (".", "..") or any(ord(c) < 32 or ord(c) == 127 for c in segment):
            raise FolderError("Unsafe folder path")
        candidate /= segment
        if candidate.is_symlink():
            raise FolderError("Folder symlinks are not supported")
    real = candidate.resolve(strict=True)
    if not real.is_relative_to(parent) or not real.is_dir():
        raise FolderError("Folder escapes the read-only source")
    return candidate


def folders(name: str, folder: str = "", *, inventory: list[dict] | None = None,
            root: Path = ROOT) -> dict:
    entries = inventory if inventory is not None else mount_inventory()
    path = resolve_folder(name, folder, inventory=entries, root=root)
    children: list[str] = []
    with os.scandir(path) as scan:
        for entry in scan:
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            if any(ord(c) < 32 or ord(c) == 127 for c in entry.name):
                continue
            children.append(entry.name)
            if len(children) >= 500:
                break
    return {"source": name, "folder": folder, "folders": sorted(children, key=str.casefold)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True)
    p.add_argument("--folder", default="")
    args = p.parse_args(argv)
    print(json.dumps(folders(args.source, args.folder), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FolderError, MountError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
