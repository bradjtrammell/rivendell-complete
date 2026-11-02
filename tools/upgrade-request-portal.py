#!/usr/bin/python3
"""Idempotently enable the local moderated listener page in our own generated unit."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile

UNIT = Path.home() / ".config/systemd/user/rdcomplete-requests.service"
PREFIX = ("ExecStart=%h/.local/bin/rdcomplete-requests "
          "--database %h/.local/state/rivendell-complete/requests.sqlite "
          "--catalog %h/.local/state/rivendell-complete/request-catalog.json "
          "--listener-token-file %h/.config/rivendell-complete/request-listener.token "
          "--admin-token-file %h/.config/rivendell-complete/request-admin.token "
          "--listen 127.0.0.1 --port 8787 ")


def update(path: Path = UNIT) -> bool:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Request service is missing or a symlink; preserving existing configuration")
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("Refusing to modify a request service with unexpected owner or permissions")
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.startswith("ExecStart=")]
    if len(matches) != 1:
        raise ValueError("Expected one service executable; keeping custom configuration unchanged")
    i = matches[0]
    line = lines[i].rstrip("\n")
    if not line.startswith(PREFIX):
        raise ValueError("Existing request service differs from the generated unit; preserving it")
    suffix = line[len(PREFIX):]
    if not suffix or not __import__("re").fullmatch(
            r"--group [A-Za-z0-9_][A-Za-z0-9_-]{0,9}( --group [A-Za-z0-9_][A-Za-z0-9_-]{0,9})*( --public-portal --moderated)?",
            suffix):
        raise ValueError("Request service has additional custom arguments; not editing it")
    if suffix.endswith(" --public-portal --moderated"):
        print("Local moderated request portal already provisioned")
        return False
    backup = path.with_name(path.name + ".before-portal")
    if backup.exists() or backup.is_symlink():
        raise ValueError("Portal backup already exists; refusing to overwrite it")
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
    lines[i] = line + " --public-portal --moderated\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".requests-portal-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            os.fchmod(target.fileno(), 0o600)
            target.write("".join(lines))
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print("Enabled local moderated listener portal (service not restarted)")
    print(f"Preserved prior service definition: {backup}")
    return True


if __name__ == "__main__":
    try:
        raise SystemExit(0 if update() or True else 0)
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
