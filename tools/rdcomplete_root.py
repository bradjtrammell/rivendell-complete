#!/usr/bin/python3
"""Root-owned Rivendell Complete local NAS commissioning helper.

Only installed under /usr/local/libexec/rivendell-complete as root:root.
Called by a graphical polkit prompt; it never accepts arbitrary command paths.
"""
from __future__ import annotations

import argparse
import configparser
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

MOUNT = Path("/mnt/radio-music")
CONF = Path("/etc/rivendell.d/rd-default.conf")
REFS = Path("/var/lib/rivendell/external-media")
HERE = Path(__file__).resolve().parent
GROUP_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,9}\Z")
NFS_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*:/[A-Za-z0-9_./-]+\Z")
SMB_PATTERN = re.compile(r"//[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_./-]+\Z")


class CommissionError(RuntimeError):
    pass


def validate_source(protocol: str, source: str) -> None:
    match = NFS_PATTERN if protocol == "nfs" else SMB_PATTERN if protocol == "smb" else None
    if match is None or not match.fullmatch(source):
        raise CommissionError("Invalid NAS source (expected a literal NFS export or SMB share)")


def verify_mount() -> str:
    if MOUNT.is_symlink() or not MOUNT.is_dir():
        raise CommissionError("NAS mountpoint is not a regular directory")
    result = subprocess.run(
        ["/usr/bin/findmnt", "-rn", "-M", str(MOUNT), "-o", "SOURCE,FSTYPE,OPTIONS"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode or not result.stdout.strip():
        raise CommissionError("NAS is not mounted at /mnt/radio-music")
    fields = result.stdout.strip().split(None, 2)
    if len(fields) != 3 or fields[1] not in ("nfs", "nfs4", "cifs"):
        raise CommissionError("The source is not an NFS/SMB mount")
    if "ro" not in fields[2].split(","):
        raise CommissionError("NAS source is not mounted read-only")
    if not MOUNT.exists():
        raise CommissionError("NAS is unavailable")
    return fields[0]


def configure_external() -> None:
    verify_mount()
    if not CONF.is_file() or CONF.is_symlink() or os.path.realpath("/etc/rd.conf") != str(CONF):
        raise CommissionError("Unexpected Rivendell configuration layout; refusing to edit it")
    p = configparser.RawConfigParser()
    if not p.read(CONF):
        raise CommissionError("Cannot read native Rivendell configuration")
    expected_root = str(MOUNT)
    expected_refs = str(REFS)
    if p.has_section("ExternalAudio"):
        if (p.get("ExternalAudio", "Root", fallback="") == expected_root
                and p.get("ExternalAudio", "References", fallback="") == expected_refs):
            print("External audio already configured; preserving existing settings")
            return
        raise CommissionError("Existing external-audio configuration differs; refusing overwrite")
    state = CONF.stat()
    if not stat.S_ISREG(state.st_mode) or state.st_uid != 0:
        raise CommissionError("Unexpected configuration ownership")
    if REFS.is_symlink():
        raise CommissionError("Reference directory cannot be a symlink")
    REFS.mkdir(parents=True, exist_ok=True, mode=0o750)
    rivendell = __import__("grp").getgrnam("rivendell").gr_gid
    os.chown(REFS, 0, rivendell)
    os.chmod(REFS, 0o750)
    original = CONF.read_bytes()
    suffix = b"\n[ExternalAudio]\nRoot=/mnt/radio-music\nReferences=/var/lib/rivendell/external-media\n"
    if len(original) > 1024 * 1024:
        raise CommissionError("Rivendell configuration unexpectedly large")
    # Make a private recovery copy; never overwrite an existing backup.
    backup = CONF.with_name(CONF.name + ".before-complete-" + __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + str(os.getpid()))
    with backup.open("xb") as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(original)
        out.flush()
        os.fsync(out.fileno())
    fd, tmp = tempfile.mkstemp(prefix=".rd-complete-", dir=str(CONF.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchown(out.fileno(), state.st_uid, state.st_gid)
            os.fchmod(out.fileno(), stat.S_IMODE(state.st_mode))
            out.write(original + suffix)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, CONF)
        p2 = configparser.RawConfigParser()
        if not p2.read(CONF) or p2.get("ExternalAudio", "Root") != expected_root:
            raise CommissionError("Could not verify the written audio configuration; recovery copy retained")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print("Configured external audio references without changing existing settings")
    print(f"Root-owned configuration recovery copy: {backup}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("mount-nfs", "mount-smb"):
        sub = commands.add_parser(name)
        sub.add_argument("--source", required=True)
    commands.add_parser("configure-external")
    for name in ("scan", "import"):
        sub = commands.add_parser(name)
        sub.add_argument("--group", required=True)
        sub.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise CommissionError("Root privileges required (use a desktop polkit prompt)")
    os.umask(0o077)
    if args.action in ("mount-nfs", "mount-smb"):
        protocol = "nfs" if args.action == "mount-nfs" else "smb"
        validate_source(protocol, args.source)
        # The mounted source is not replaced if it is already present.
        try:
            existing = verify_mount()
        except CommissionError:
            existing = None
        if existing is not None:
            if existing != args.source:
                raise CommissionError(f"Another NAS source is already mounted: {existing}")
            print("Existing read-only NAS mount preserved")
        else:
            script = HERE / "setup-nas.sh"
            if script.is_symlink() or not script.is_file() or script.stat().st_uid != 0:
                raise CommissionError("Privileged NAS installer is not root-owned")
            proc = subprocess.run(
                ["/usr/bin/bash", str(script), "--" + protocol, args.source],
                stdin=sys.stdin, timeout=480, check=False,
            )
            if proc.returncode:
                raise CommissionError(f"NAS mounting failed (exit {proc.returncode})")
        verify_mount()
        configure_external()
    elif args.action == "configure-external":
        configure_external()
    else:
        if not GROUP_PATTERN.fullmatch(args.group):
            raise CommissionError("Invalid Rivendell group")
        if args.limit is not None and not 1 <= args.limit <= 100000:
            raise CommissionError("Import limit must be between 1 and 100000")
        verify_mount()
        if args.action == "import" and subprocess.run(
            ["/usr/bin/pgrep", "-x", "rdairplay"], check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0:
            raise CommissionError("Stop RDAirPlay before modifying the music catalog")
        script = HERE / "rdexternal.py"
        if script.is_symlink() or not script.is_file() or script.stat().st_uid != 0:
            raise CommissionError("Privileged media indexer is not root-owned")
        cmd = ["/usr/bin/python3", str(script), "--root", str(MOUNT), "--group", args.group]
        if args.limit is not None:
            cmd.extend(["--limit", str(args.limit)])
        if args.action == "import":
            cmd.append("--commit")
        proc = subprocess.run(cmd, check=False, timeout=3600)
        if proc.returncode:
            raise CommissionError(f"{args.action} failed (exit {proc.returncode}); review the output")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CommissionError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
