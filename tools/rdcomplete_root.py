#!/usr/bin/python3
"""Root-owned Rivendell Complete local NAS commissioning helper.

Only installed under /usr/local/libexec/rivendell-complete as root:root.
Called by a graphical polkit prompt; it never accepts arbitrary command paths.
"""
from __future__ import annotations

import argparse
import configparser
import json
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
# The installed root helper and mount inventory are root-owned siblings.
sys.path.insert(0, str(HERE))
from rdmounts import (MountError, mount_path, fstab_mounts, validate_source as validate_remote)
GROUP_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,9}\Z")
NFS_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*:/[A-Za-z0-9_./-]+\Z")
SMB_PATTERN = re.compile(r"//[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_./-]+\Z")


class CommissionError(RuntimeError):
    pass


def validate_source(protocol: str, source: str) -> None:
    try:
        validate_remote(protocol, source)
    except MountError as exc:
        raise CommissionError(str(exc)) from exc


def verify_mount(name: str | None = None) -> str:
    try:
        target = mount_path(name) if name is not None else MOUNT
    except MountError as exc:
        raise CommissionError(str(exc)) from exc
    if MOUNT.is_symlink() or target.is_symlink() or not target.is_dir():
        raise CommissionError(f"NAS mountpoint is missing or a symlink: {target}")
    # Wake a configured systemd automount without writing any source data.
    # This intentionally fails if the NAS is unavailable.
    (target / ".").stat()
    # Inspect the exact mountpoint rather than a containing parent filesystem.
    result = subprocess.run(
        ["/usr/bin/findmnt", "-rn", "-M", str(target), "-o", "SOURCE,FSTYPE,OPTIONS"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode or not result.stdout.strip():
        raise CommissionError(f"NAS source is not mounted: {target}")
    fields = result.stdout.strip().split(None, 2)
    if len(fields) != 3 or fields[1] not in ("nfs", "nfs4", "cifs"):
        raise CommissionError(f"Not an active NFS/SMB mount: {target}")
    if "ro" not in fields[2].split(",") or not (os.statvfs(target).f_flag & os.ST_RDONLY):
        raise CommissionError(f"NAS mount is writable; refusing: {target}")
    return fields[0]


def verify_sources() -> None:
    items = fstab_mounts()
    if not items:
        # Support a manually mounted legacy single-root configuration.
        verify_mount()
        return
    # Do not report a partially offline collection as ready for live playout.
    if any(not item["readonly_configured"] for item in items):
        raise CommissionError("An NFS/SMB source in fstab lacks read-only options")
    for item in items:
        name = None if item["legacy"] else item["name"]
        actual = verify_mount(name)
        if actual != item["source"]:
            raise CommissionError(f"NAS source changed unexpectedly: {item['name']}")



def _source_available(item: dict) -> bool:
    try:
        name = None if item["legacy"] else item["name"]
        return verify_mount(name) == item["source"]
    except (CommissionError, OSError, subprocess.TimeoutExpired):
        return False


def configure_external() -> None:
    items = fstab_mounts()
    if items:
        if any(not item["readonly_configured"] for item in items):
            raise CommissionError("A configured NAS source is not read-only")
        # Do not require an unrelated NAS to be online to add a new share.
        if not any(_source_available(item) for item in items):
            raise CommissionError("No configured NFS/SMB source is online")
    else:
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
        sub.add_argument("--name", help="Stable name for additional NAS share")
    commands.add_parser("configure-external")
    commands.add_parser("export-catalog")
    commands.add_parser("list-groups")
    schedule = commands.add_parser("schedule-catalog")
    schedule.add_argument("--groups", required=True,
                          help="Comma-separated existing music groups")
    schedule.add_argument("--id-cart", type=int, required=True,
                          help="Actual top-of-hour legal ID cart")
    schedule.add_argument("--jingle-cart", type=int, default=0)
    schedule.add_argument("--fill-cart", type=int, default=0)
    commands.add_parser("restart-audio")
    commands.add_parser("materialize-audio")
    for name in ("scan", "import"):
        sub = commands.add_parser(name)
        sub.add_argument("--group", required=True)
        sub.add_argument("--name", help="Only import from the named read-only NAS share")
        sub.add_argument("--folder", default="", help="Optional existing folder inside the share")
        sub.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise CommissionError("Root privileges required (use a desktop polkit prompt)")
    os.umask(0o077)
    if args.action in ("mount-nfs", "mount-smb"):
        protocol = "nfs" if args.action == "mount-nfs" else "smb"
        validate_source(protocol, args.source)
        try:
            target = mount_path(args.name) if args.name else MOUNT
        except MountError as exc:
            raise CommissionError(str(exc)) from exc
        items = fstab_mounts()
        if args.name and any(item["legacy"] for item in items):
            raise CommissionError("A legacy root-mounted NAS must be migrated separately; preserving its references")
        if not args.name and any(not item["legacy"] for item in items):
            raise CommissionError("Cannot mount over a named NAS collection")
        matching = [item for item in items if item["path"] == str(target)]
        if matching:
            if len(matching) != 1 or matching[0]["source"] != args.source:
                raise CommissionError("This NAS mount name already belongs to a different share")
            actual = verify_mount(args.name)
            if actual != args.source:
                raise CommissionError("Configured mount is not online or maps to a different source")
            print(f"Existing read-only source preserved: {target}")
        else:
            script = HERE / "setup-nas.sh"
            if script.is_symlink() or not script.is_file() or script.stat().st_uid != 0:
                raise CommissionError("Privileged NAS installer is not root-owned")
            cmd = ["/usr/bin/bash", str(script), "--" + protocol, args.source]
            if args.name:
                cmd += ["--mountpoint", str(target)]
            proc = subprocess.run(cmd, stdin=sys.stdin, timeout=480, check=False)
            if proc.returncode:
                raise CommissionError(f"NAS mounting failed (exit {proc.returncode})")
            if verify_mount(args.name) != args.source:
                raise CommissionError("Mount source mismatch following NAS setup")
        configure_external()
    elif args.action == "configure-external":
        configure_external()
    elif args.action == "restart-audio":
        if subprocess.run(
            ["/usr/bin/pgrep", "-x", "rdairplay"], check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0:
            raise CommissionError("Stop RDAirPlay before restarting the audio daemon")
        verify_sources()
        subprocess.run(["/usr/bin/systemctl", "restart", "rivendell"],
                       check=True, timeout=40)
        subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", "rivendell"],
                       check=True, timeout=15)
        print("Rivendell audio daemon restarted with the NAS configuration")
    elif args.action == "materialize-audio":
        verify_sources()
        script = HERE / "rdcomplete_materialize.py"
        if script.is_symlink() or not script.is_file() or script.stat().st_uid != 0:
            raise CommissionError("Native audio recovery tool is missing or not root-owned")
        result = subprocess.run(
            ["/usr/bin/python3", str(script), "--commit"],
            check=False, timeout=21600)
        if result.returncode:
            raise CommissionError("Audio materialization incomplete; retry safely after correcting errors")
    elif args.action == "list-groups":
        script = HERE / "rdexternal.py"
        if script.is_symlink() or not script.is_file() or script.stat().st_uid != 0:
            raise CommissionError("Rivendell group reader is not root-owned")
        import pymysql
        from rdexternal import read_db_settings
        db = pymysql.connect(**read_db_settings(Path("/etc/rd.conf")))
        try:
            with db.cursor() as cur:
                cur.execute("SELECT NAME FROM GROUPS ORDER BY NAME")
                groups = [str(row[0]).strip() for row in cur.fetchall()]
        finally:
            db.close()
        print(json.dumps({"groups": [g for g in groups if GROUP_PATTERN.fullmatch(g)]}))
    elif args.action == "schedule-catalog":
        import pymysql
        from rdcatalog import export_catalog, load_external_map
        from rdexternal import read_db_settings, media_path
        if len(args.groups) > 512:
            raise CommissionError("Too many rotation group names")
        groups = args.groups.split(",")
        if not groups or len(groups) > 24 or len(set(groups)) != len(groups):
            raise CommissionError("Choose 1-24 distinct existing music groups")
        if any(not GROUP_PATTERN.fullmatch(group) for group in groups):
            raise CommissionError("Invalid music group in rotation")
        for cart in (args.id_cart, args.jingle_cart, args.fill_cart):
            if cart < 0 or cart > 999999:
                raise CommissionError("Invalid station cart number")
        if args.id_cart == 0:
            raise CommissionError("Actual station identification cart is required")
        tracks = export_catalog(Path("/etc/rd.conf"), groups)
        if not tracks:
            raise CommissionError("No playable audio in the selected music categories")
        db = pymysql.connect(**read_db_settings(Path("/etc/rd.conf")))
        root, external = load_external_map(Path("/etc/rd.conf"))
        selections = {}
        try:
            with db.cursor() as cursor:
                for label, number in (("top_hour", args.id_cart),
                                      ("jingle", args.jingle_cart),
                                      ("fill_bed", args.fill_cart)):
                    if number == 0:
                        continue
                    cursor.execute(
                        "SELECT NUMBER,AVERAGE_LENGTH,VALIDITY,TYPE,GROUP_NAME "
                        "FROM CART WHERE NUMBER=%s", (number,))
                    row = cursor.fetchone()
                    if row is None or int(row[3]) != 1 or int(row[2]) not in (2, 3):
                        raise CommissionError(f"{label} cart is not a valid playable audio cart")
                    length = int(row[1])
                    if not 500 <= length <= 3600000:
                        raise CommissionError(f"{label} cart has invalid duration")
                    if root is not None and number in external:
                        source = media_path(root, external[number])
                        if source.suffix.lower() not in (".mp3", ".ogg", ".wav"):
                            raise CommissionError(f"{label} cart audio format not supported")
                    elif not (Path("/var/snd") / f"{number:06d}_001.wav").is_file():
                        raise CommissionError(f"{label} cart has no accessible audio file")
                    selections[label] = {"cart": number, "duration_ms": length,
                                         "group": str(row[4]).strip()}
        finally:
            db.close()
        print(json.dumps({"tracks": tracks, "groups": groups,
                          "specials": selections}, ensure_ascii=False))
    elif args.action == "export-catalog":
        script = HERE / "rdcatalog.py"
        if script.is_symlink() or not script.is_file() or script.stat().st_uid != 0:
            raise CommissionError("Privileged catalog exporter is not root-owned")
        completed = subprocess.run(
            ["/usr/bin/python3", str(script), "--group", "MUSIC"],
            timeout=300, check=False,
        )
        if completed.returncode:
            raise CommissionError(f"Catalog export failed (exit {completed.returncode})")
    else:
        if not GROUP_PATTERN.fullmatch(args.group):
            raise CommissionError("Invalid Rivendell group")
        if args.limit is not None and not 1 <= args.limit <= 100000:
            raise CommissionError("Import limit must be between 1 and 100000")
        if args.name is None and any(not item["legacy"] for item in fstab_mounts()):
            raise CommissionError("Choose a named NAS source to import")
        verify_mount(args.name)
        if args.action == "import" and subprocess.run(
            ["/usr/bin/pgrep", "-x", "rdairplay"], check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0:
            raise CommissionError("Stop RDAirPlay before modifying the music catalog")
        script = HERE / "rdexternal.py"
        if script.is_symlink() or not script.is_file() or script.stat().st_uid != 0:
            raise CommissionError("Privileged media indexer is not root-owned")
        root = mount_path(args.name) if args.name else MOUNT
        mount_root = root.resolve(strict=True)
        folder = args.folder
        if folder:
            if len(folder) > 1024 or folder.startswith("/") or chr(92) in folder:
                raise CommissionError("Unsafe import folder")
            for segment in folder.split("/"):
                if segment in ("", ".", "..") or any(ord(c) < 32 or ord(c) == 127 for c in segment):
                    raise CommissionError("Unsafe import folder component")
                root = root / segment
                if root.is_symlink():
                    raise CommissionError("Folder symlinks are not accepted")
            if not root.resolve(strict=True).is_relative_to(mount_root) or not root.is_dir():
                raise CommissionError("Selected import folder escapes source mount")
        cmd = ["/usr/bin/python3", str(script), "--root", str(root), "--group", args.group]
        prefix = "/".join(filter(None, [args.name or "", folder]))
        if prefix:
            cmd.extend(["--reference-prefix", prefix])
        if args.limit is not None:
            cmd.extend(["--limit", str(args.limit)])
        if args.action == "import":
            cmd.append("--commit")
        proc = subprocess.run(cmd, check=False, timeout=3600)
        if proc.returncode:
            raise CommissionError(f"{args.action} failed (exit {proc.returncode}); review the output")
        if args.action == "import":
            native = HERE / "rdcomplete_materialize.py"
            if native.is_symlink() or not native.is_file() or native.stat().st_uid != 0:
                raise CommissionError("Native audio conversion tool is missing or unsafe")
            result = subprocess.run(
                ["/usr/bin/python3", str(native), "--commit"],
                check=False, timeout=21600)
            if result.returncode:
                raise CommissionError("Catalog indexed but native audio incomplete. Existing cuts are preserved.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CommissionError, MountError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
