#!/usr/bin/env python3
"""Configure and run GlassCoder on a single Rivendell Complete workstation."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from urllib.parse import urlsplit

SERVER_TYPES = ("IceCast2", "Shout1", "Shout2")
DEVICES = ("ALSA", "JACK")
DEFAULT_DIR = Path.home() / ".config" / "rivendell-complete"


class StreamError(RuntimeError):
    pass


def validate_config(config: dict) -> None:
    if not isinstance(config, dict):
        raise StreamError("Stream configuration must be a JSON object")
    if config.get("server_type") not in SERVER_TYPES:
        raise StreamError("Unsupported server type")
    if config.get("audio_device") not in DEVICES:
        raise StreamError("Unsupported audio device")
    if type(config.get("bitrate")) is not int or not 32 <= config["bitrate"] <= 320:
        raise StreamError("Bitrate must be 32-320 kbps")
    if config.get("samplerate") not in (32000, 44100, 48000):
        raise StreamError("Sample rate must be 32000, 44100 or 48000")
    url = urlsplit(config.get("server_url", ""))
    if (url.scheme != "http" or not url.hostname or not url.port or
            url.username or url.password or url.query or url.fragment or
            not 1 <= url.port <= 65535):
        raise StreamError("Use an http://HOST:PORT/path URL, with NO credentials or query")
    if any(c in config.get("jack_client", "") for c in "\x00\r\n") or not config.get("jack_client"):
        raise StreamError("Invalid JACK client name")
    if any(c in config.get("alsa_device", "") for c in "\x00\r\n") or not config.get("alsa_device"):
        raise StreamError("Invalid ALSA device")
    for name in ("stream_name", "genre"):
        value = config.get(name, "")
        if not isinstance(value, str) or any(c in value for c in "\x00\r\n"):
            raise StreamError(f"Invalid {name}")


def glasscoder_command(config: dict, credentials: Path) -> list[str]:
    validate_config(config)
    args = [
        "glasscoder",
        f"--server-type={config['server_type']}",
        f"--server-url={config['server_url']}",
        "--audio-format=MP3",
        f"--audio-bitrate={config['bitrate']}",
        "--audio-channels=2",
        f"--audio-samplerate={config['samplerate']}",
        f"--audio-device={config['audio_device']}",
        f"--credentials-file={credentials}",
    ]
    if config["audio_device"] == "JACK":
        args.append(f"--jack-client-name={config['jack_client']}")
    else:
        args.append(f"--alsa-device={config['alsa_device']}")
    if config.get("stream_name"):
        args.append(f"--stream-name={config['stream_name']}")
    if config.get("genre"):
        args.append(f"--stream-genre={config['genre']}")
    return args


def safe_write(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())


def configure(args: argparse.Namespace) -> int:
    directory = args.config_dir.expanduser().absolute()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise StreamError("Config directory must be private (mode 0700), not a symlink")
    config_path = directory / "stream.json"
    secret_path = directory / "credentials.ini"
    if config_path.exists() or secret_path.exists():
        raise StreamError("Configuration exists; refusing to overwrite credentials")
    config = {
        "server_type": args.server_type, "server_url": args.server_url,
        "audio_device": args.audio_device, "alsa_device": args.alsa_device,
        "jack_client": args.jack_client, "bitrate": args.bitrate,
        "samplerate": args.samplerate, "stream_name": args.stream_name,
        "genre": args.genre,
    }
    validate_config(config)
    if not args.username or re.search(r"[\x00-\x1f=]", args.username):
        raise StreamError("Username is empty or contains invalid characters")
    password = getpass.getpass("Stream source password: ")
    if not password or re.search(r"[\x00-\x1f]", password):
        raise StreamError("Password is empty or contains invalid characters")
    secret = f"[Credentials]\nUsername={args.username}\nPassword={password}\n"
    safe_write(secret_path, secret.encode("utf-8"))
    try:
        safe_write(config_path, (json.dumps(config, indent=2) + "\n").encode("utf-8"))
    except Exception:
        secret_path.unlink(missing_ok=True)
        raise
    print("Saved private GlassCoder configuration; start it with the user systemd service.")
    return 0


def start(config_dir: Path, check_only: bool) -> int:
    directory = config_dir.expanduser().absolute()
    config_path, secret_path = directory / "stream.json", directory / "credentials.ini"
    for path in (config_path, secret_path):
        s = path.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_mode & 0o077 or s.st_uid != os.getuid():
            raise StreamError(f"Unsafe ownership or permissions: {path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    command = glasscoder_command(config, secret_path)
    if shutil.which("glasscoder") is None:
        raise StreamError("glasscoder is not installed (apt install glasscoder)")
    if check_only:
        print("Validated GlassCoder configuration; audio routing and server login NOT tested.")
        print(" ".join(command))
        return 0
    os.execvp(command[0], command)
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config-dir", type=Path, default=DEFAULT_DIR)
    sub = ap.add_subparsers(dest="action", required=True)
    cfg = sub.add_parser("configure", help="Write a protected encoder configuration")
    cfg.add_argument("--server-type", required=True, choices=SERVER_TYPES)
    cfg.add_argument("--server-url", required=True)
    cfg.add_argument("--username", required=True)
    cfg.add_argument("--audio-device", choices=DEVICES, default="JACK")
    cfg.add_argument("--jack-client", default="rivendell-complete")
    cfg.add_argument("--alsa-device", default="default")
    cfg.add_argument("--bitrate", type=int, default=128)
    cfg.add_argument("--samplerate", type=int, default=44100)
    cfg.add_argument("--stream-name", default="")
    cfg.add_argument("--genre", default="")
    sub.add_parser("verify", help="Check credentials/config and display safe command")
    sub.add_parser("run", help="Exec GlassCoder using protected credentials file")
    args = ap.parse_args(argv)
    if args.action == "configure":
        return configure(args)
    return start(args.config_dir, check_only=(args.action == "verify"))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (StreamError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
