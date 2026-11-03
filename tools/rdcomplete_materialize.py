#!/usr/bin/python3
"""Materialize existing NAS reference carts as native Rivendell WAV cuts.

The original NAS files remain read-only and are never modified. This repairs
the gap between CART/CUTS metadata and the /var/snd audio files CAE plays.
Dry-run by default. Existing native cuts are NEVER overwritten.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import wave

from rdexternal import ImportFailure, media_path, references, read_db_settings
from rdmounts import mount_inventory

REFS = Path("/var/lib/rivendell/external-media")
SOURCES = Path("/mnt/radio-music")
AUDIO = Path("/var/snd")


class MaterializeError(RuntimeError):
    pass


def check_store(store: Path) -> os.stat_result:
    if store.is_symlink() or not store.is_dir():
        raise MaterializeError("Native /var/snd storage is absent or symlinked")
    info = store.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o002:
        raise MaterializeError("Native audio storage has unsafe permissions")
    if not os.access(store, os.W_OK):
        raise MaterializeError("Native audio storage is not writable")
    return info


def online_ro_sources() -> None:
    items = mount_inventory()
    if not items:
        raise MaterializeError("No persistent NAS mounts registered")
    offline = [entry["name"] for entry in items
               if not entry["mounted"] or not entry["readonly"]]
    if offline:
        raise MaterializeError("NAS sources offline or writable: " + ", ".join(offline))


def destination(store: Path, cart: int) -> Path:
    if not 1 <= cart <= 999999:
        raise MaterializeError("Out-of-range Rivendell cart number")
    return store / f"{cart:06d}_001.wav"


def is_native_pcm(target: Path) -> bool:
    try:
        if target.is_symlink() or not target.is_file():
            return False
        with wave.open(str(target), 'rb') as track:
            return (track.getnchannels() == 2 and track.getsampwidth() == 2
                    and track.getframerate() == 48000 and track.getnframes() >= 24000)
    except (OSError, ValueError, wave.Error):
        return False


def sync_metadata(conn, cart: int) -> None:
    cut = f'{cart:06d}_001'
    with conn.cursor() as cur:
        cur.execute('SELECT C.TYPE,T.CART_NUMBER FROM CART C '
                    'JOIN CUTS T ON T.CUT_NAME=%s WHERE C.NUMBER=%s',
                    (cut, cart))
        row = cur.fetchone()
        if row is None or int(row[0]) != 1 or int(row[1]) != cart:
            raise MaterializeError(f'Cart {cart} lacks its indexed audio cut')
        cur.execute('UPDATE CUTS SET CODING_FORMAT=0,SAMPLE_RATE=48000,'
                    'BIT_RATE=1536000,CHANNELS=2 WHERE CUT_NAME=%s AND CART_NUMBER=%s',
                    (cut, cart))
        if cur.rowcount not in (0, 1):
            raise MaterializeError('Audio cut metadata update was ambiguous')
    conn.commit()


def convert(source: Path, target: Path, store_info: os.stat_result,
            *, timeout: int = 300) -> None:
    if target.exists() or target.is_symlink():
        raise MaterializeError(f"Native audio cut already exists: {target}")
    # No fixed filename and no overwriting an already present cart.
    fd, name = tempfile.mkstemp(prefix=".rdcomplete-cut-", suffix=".wav",
                                dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        if temporary.is_symlink():
            raise MaterializeError("Unsafe temporary audio path")
        command = [
            "/usr/bin/ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(source), "-map", "0:a:0", "-vn",
            "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le",
            "-f", "wav", "-y", str(temporary),
        ]
        proc = subprocess.run(command, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=timeout, check=False)
        if proc.returncode:
            raise MaterializeError(
                "Audio conversion failed: " +
                proc.stderr.decode("utf-8", "replace")[-300:])
        with wave.open(str(temporary), "rb") as track:
            if (track.getnchannels() != 2 or track.getsampwidth() != 2
                    or track.getframerate() != 48000
                    or track.getnframes() < 24000):
                raise MaterializeError("Converted audio is not a valid stereo PCM cut")
        os.chown(temporary, store_info.st_uid, store_info.st_gid)
        os.chmod(temporary, 0o644)
        with temporary.open("rb") as audio:
            os.fsync(audio.fileno())
        # link() is atomic and EXCLUSIVE; os.replace() would overwrite a
        # newly created cart from a competing import or studio operator.
        os.link(temporary, target, follow_symlinks=False)
        dirfd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        temporary.unlink(missing_ok=True)


def materialize(*, commit: bool, root: Path = SOURCES,
                refs: Path = REFS, store: Path = AUDIO,
                limit: int | None = None) -> dict:
    if os.geteuid() != 0:
        raise MaterializeError("Run as root to verify NAS and create native audio cuts")
    if not Path("/usr/bin/ffmpeg").is_file() or not os.access("/usr/bin/ffmpeg", os.X_OK):
        raise MaterializeError("Expected /usr/bin/ffmpeg is not installed")
    if subprocess.run(["/usr/bin/pgrep", "-x", "rdairplay"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      check=False).returncode == 0 and commit:
        raise MaterializeError("Close RDAirPlay before creating native audio cuts")
    online_ro_sources()
    check_store(store)
    if root.is_symlink() or refs.is_symlink() or not refs.is_dir():
        raise MaterializeError("NAS root or reference directory is missing/unsafe")
    records = references(refs)
    if not records:
        raise MaterializeError("No imported external-media reference carts exist")
    if limit is not None and limit < 1:
        raise MaterializeError("Limit must be positive")
    stats = store.stat()
    if commit:
        import pymysql
        conn = pymysql.connect(**read_db_settings(Path("/etc/rd.conf")))
    else:
        conn = None
    summary = {"referenced": len(records), "already_native": 0,
               "missing_sources": 0, "pending": 0, "converted": 0, "reconciled": 0, "failed": 0}
    remaining = limit
    for relative, cart in sorted(records.items(), key=lambda pair: pair[1]):
        target = destination(store, cart)
        if target.is_symlink():
            raise MaterializeError(f"Unsafe symlink at native audio cut: {target}")
        if target.exists():
            if not target.is_file() or target.stat().st_size == 0:
                raise MaterializeError(f"Unsafe or empty existing cut: {target}")
            summary["already_native"] += 1
            if commit and is_native_pcm(target):
                try:
                    sync_metadata(conn, cart)
                    summary["reconciled"] += 1
                except (OSError, ValueError, MaterializeError) as exc:
                    summary["failed"] += 1
                    print(f"FAILED to reconcile cart {cart}: {exc}", file=sys.stderr)
            continue
        try:
            source = media_path(root, relative)
        except (OSError, ValueError, ImportFailure):
            summary["missing_sources"] += 1
            continue
        if source.suffix.lower() not in {".mp3", ".ogg", ".wav"}:
            summary["missing_sources"] += 1
            continue
        summary["pending"] += 1
        if not commit or (remaining is not None and remaining <= 0):
            continue
        # Reserve enough disk for the worst-case 24-hour PCM track and keep
        # a 1 GiB margin. The check is per track, so interrupted batches resume.
        try:
            import json
            probe = subprocess.run(
                ["/usr/bin/ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "json", str(source)],
                capture_output=True, text=True, timeout=30, check=False)
            duration = float(json.loads(probe.stdout)["format"]["duration"])
            if probe.returncode or not 0.5 <= duration <= 86400:
                raise MaterializeError("Original audio has invalid duration")
            expected = int(duration * 48000 * 4) + (1 << 30)
            if shutil.disk_usage(store).free < expected:
                raise MaterializeError("Insufficient native audio storage capacity")
            convert(source, target, stats)
            sync_metadata(conn, cart)
            summary["converted"] += 1
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired,
                MaterializeError) as exc:
            summary["failed"] += 1
            print(f"FAILED cart {cart:06d}: {exc}", file=sys.stderr)
        if remaining is not None:
            remaining -= 1
        if summary["converted"] % 25 == 0 and summary["converted"] != 0:
            print(f"Converted {summary['converted']} cuts", flush=True)
    if conn is not None:
        conn.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true",
                        help="Create missing native WAV cuts; original media stays untouched")
    parser.add_argument("--limit", type=int, default=None,
                        help="Maximum new cuts to convert in this run")
    args = parser.parse_args(argv)
    import json
    report = materialize(commit=args.commit, limit=args.limit)
    print(json.dumps(report, indent=2))
    if report["missing_sources"] or report["failed"]:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ImportFailure, MaterializeError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
