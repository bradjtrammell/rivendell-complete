#!/usr/bin/env python3
"""Publish a single now-playing title to private GlassCoder metadata FIFO.

Intended as a safe target for the Rivendell PyPAD Now/Next callback.
"""
from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
import stat
import sys
import time


class MetadataError(ValueError):
    pass


def normalize(artist: str, title: str) -> bytes:
    if not isinstance(artist, str) or not isinstance(title, str):
        raise MetadataError("Artist and title must be text")
    if not artist.strip() or not title.strip():
        raise MetadataError("Artist and title cannot be empty")
    combined=f"{artist.strip()} - {title.strip()}"
    if len(combined.encode("utf-8")) > 512:
        raise MetadataError("Metadata too long")
    if any(ord(c) < 32 or ord(c) == 127 for c in combined):
        raise MetadataError("Metadata contains control characters")
    return combined.encode("utf-8") + b"\n"


def publish(fifo: Path, artist: str, title: str) -> None:
    payload=normalize(artist,title)
    st=fifo.lstat()
    if not stat.S_ISFIFO(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o177:
        raise MetadataError("Not a private FIFO owned by the current user")
    try:
        fd=os.open(fifo,os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno in (errno.ENXIO, errno.ENOENT):
            raise MetadataError("GlassCoder metadata receiver is not running") from exc
        raise
    try:
        count=os.write(fd,payload)
        if count!=len(payload):
            raise MetadataError("Partial metadata write")
    finally:
        os.close(fd)


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artist",required=True)
    parser.add_argument("--title",required=True)
    parser.add_argument("--fifo",type=Path,default=Path.home()/".local/state/rivendell-complete/encoder-metadata.fifo")
    args=parser.parse_args(argv)
    publish(args.fifo,args.artist,args.title)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (MetadataError,OSError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        raise SystemExit(1)
