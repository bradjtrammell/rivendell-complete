#!/usr/bin/python3
"""Discover remote NAS exports/shares and read-only folders for station mapping.

SMB credentials arrive as bounded JSON via stdin, never command arguments,
shell strings or environment variables. A 0600 temporary smbclient auth file
exists only during discovery. This tool never mounts or writes source audio.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HOST = re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,252})\Z")
SHARE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}\Z")
DIRECTORY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_ .-]{0,150}\Z")
DAYS = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
SMB_DIRECTORY = re.compile(r"^\s*(.*?)\s+([A-Z]+)\s+\d+\s+" + DAYS + r"\s+", re.I)


class BrowseError(ValueError):
    pass


def hostname(server: str) -> str:
    if not isinstance(server, str) or HOST.fullmatch(server) is None:
        raise BrowseError("Enter a valid NAS hostname or IPv4 address")
    return server


def share_name(name: str) -> str:
    """Validate one SMB share, allowing a harmless trailing path separator.

    Underscores are legal SMB share-name characters. Do not accept nested
    paths here: those belong in the separate relative folder parameter.
    """
    if not isinstance(name, str):
        raise BrowseError("Select a valid SMB share name")
    canonical = name.rstrip("/")
    if SHARE.fullmatch(canonical) is None:
        raise BrowseError(
            "Invalid SMB share name: use letters, numbers, underscores, "
            "hyphens or periods; select subfolders separately")
    return canonical


def folder_path(relative: str) -> str:
    if not isinstance(relative, str) or len(relative) > 1024:
        raise BrowseError("Invalid remote folder")
    if not relative or relative == ".":
        return ""
    parsed = PurePosixPath(relative)
    if (relative.startswith("/") or "\\" in relative
            or any(component in (".", "..") or DIRECTORY.fullmatch(component) is None
                   for component in relative.split("/"))):
        raise BrowseError("Remote path must contain safe relative folders only")
    if ".." in parsed.parts:
        raise BrowseError("Parent traversal is forbidden")
    return relative


def read_auth() -> tuple[str, str]:
    raw = sys.stdin.buffer.read(8193)
    if len(raw) > 8192:
        raise BrowseError("SMB credentials exceed safe input size")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or set(data) != {"username", "password"}:
        raise BrowseError("Expected username and password")
    user, secret = data["username"], data["password"]
    if (not isinstance(user, str) or not isinstance(secret, str)
            or not 1 <= len(user) <= 128 or not 1 <= len(secret) <= 1024
            or any(c in user + secret for c in "\r\n\0")):
        raise BrowseError("Invalid SMB credentials")
    return user, secret


@contextmanager
def smb_auth(username: str, password: str):
    run_path = Path(f"/run/user/{os.getuid()}")
    if not run_path.is_dir() or not (run_path.stat().st_mode & 0o077) == 0:
        run_path = Path("/dev/shm")
    with tempfile.TemporaryDirectory(prefix=".rdcomplete-smb-", dir=run_path) as folder:
        root = Path(folder)
        os.chmod(root, 0o700)
        auth = root / "auth.conf"
        fd = os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(f"username = {username}\npassword = {password}\n")
                out.flush()
                os.fsync(out.fileno())
            yield auth
        finally:
            # TemporaryDirectory securely removes the file; do not echo secrets.
            pass


def command(arguments: list[str]) -> str:
    if not arguments or shutil.which(arguments[0]) is None:
        raise BrowseError("Required NAS discovery utility is not installed")
    try:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=20,
                                check=False)
    except subprocess.TimeoutExpired as exc:
        raise BrowseError("NAS discovery timed out; check network and share permissions") from exc
    if result.returncode:
        raise BrowseError("NAS discovery failed; check server address and permissions")
    if len(result.stdout) > 2 * 1024 * 1024:
        raise BrowseError("NAS returned too many entries")
    return result.stdout


def parse_smb_shares(output: str) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    for line in output.splitlines():
        pieces = line.split("|", 2)
        if len(pieces) != 3 or pieces[0] != "Disk":
            continue
        share = pieces[1].strip()
        if not share or share.casefold() in seen:
            continue
        seen.add(share.casefold())
        found.append({"name": share, "mountable": SHARE.fullmatch(share) is not None,
                      "description": pieces[2][:120]})
        if len(found) >= 500:
            break
    return found


def parse_smb_folders(output: str) -> list[str]:
    folders: set[str] = set()
    for line in output.splitlines():
        match = SMB_DIRECTORY.match(line)
        if not match:
            continue
        name, attributes = match.groups()
        name = name.strip()
        if name in ("", ".", "..") or "D" not in attributes.upper():
            continue
        if DIRECTORY.fullmatch(name) is None:
            continue
        folders.add(name)
        if len(folders) >= 500:
            break
    return sorted(folders, key=str.casefold)


def parse_nfs_exports(output: str) -> list[dict]:
    result = []
    for line in output.splitlines()[1:]:
        parts = line.split(None, 1)
        if not parts:
            continue
        source = parts[0]
        if not source.startswith("/") or not re.fullmatch(r"/[A-Za-z0-9_./-]+", source):
            continue
        if ".." in PurePosixPath(source).parts:
            continue
        result.append({"name": source, "description": parts[1][:120] if len(parts) > 1 else "",
                       "mountable": True})
        if len(result) >= 500:
            break
    return result


def discover(protocol: str, server: str, mode: str,
             share: str = "", folder: str = "", auth: tuple[str, str] | None = None) -> dict:
    server = hostname(server)
    if protocol == "nfs":
        if mode != "shares":
            raise BrowseError("Browse NFS subdirectories after mounting the selected export")
        output = command(["/usr/sbin/showmount", "-e", server])
        return {"protocol": "nfs", "server": server, "shares": parse_nfs_exports(output)}
    if protocol != "smb" or mode not in ("shares", "folders"):
        raise BrowseError("Unsupported NAS discovery request")
    if auth is None:
        raise BrowseError("SMB credentials required")
    with smb_auth(*auth) as file:
        if mode == "shares":
            text = command(["smbclient", "-g", "-L", f"//{server}", "-A", str(file),
                            "-m", "SMB3", "-d", "0"])
            return {"protocol": "smb", "server": server, "shares": parse_smb_shares(text)}
        share = share_name(share)
        folder = folder_path(folder)
        args = ["smbclient", f"//{server}/{share}", "-A", str(file),
                "-m", "SMB3", "-d", "0"]
        if folder:
            args += ["-D", folder]
        args += ["-c", "ls"]
        text = command(args)
        return {"protocol": "smb", "server": server, "share": share,
                "folder": folder, "folders": parse_smb_folders(text)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--protocol", choices=("smb", "nfs"), required=True)
    ap.add_argument("--mode", choices=("shares", "folders"), default="shares")
    ap.add_argument("--server", required=True)
    ap.add_argument("--share", default="")
    ap.add_argument("--folder", default="")
    args = ap.parse_args(argv)
    credentials = read_auth() if args.protocol == "smb" else None
    print(json.dumps(discover(args.protocol, args.server, args.mode, args.share,
                              args.folder, credentials), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BrowseError, ValueError, UnicodeError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
