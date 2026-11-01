#!/usr/bin/env python3
"""Rivendell PyPAD → GlassCoder metadata FIFO, with no SHOUTcast secrets.

Register in RDAdmin as a PyPAD script; the normal Rivendell Receiver handles
Now/Next changes and forwards only permitted on-air events.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys

try:
    from rivendellaudio import pypad
except ModuleNotFoundError:
    import pypad


def send_now_playing(update):
    section="GlassCoder"
    if not update.config().has_section(section):
        return
    if not update.hasPadType(pypad.TYPE_NOW):
        return
    if not update.shouldBeProcessed(section):
        return
    template=update.config().get(section,"FormatString",fallback="%a - %t")
    title=update.resolvePadFields(template,pypad.ESCAPE_NONE).strip()
    if not title or len(title.encode("utf-8"))>512:
        return
    if any(ord(c)<32 or ord(c)==127 for c in title):
        return
    fifo=Path(update.config().get(
        section,"MetadataFifo",fallback=str(
            Path.home()/".local/state/rivendell-complete/encoder-metadata.fifo")))
    try:
        info=fifo.lstat()
        if not stat.S_ISFIFO(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o177:
            raise OSError("Unsafe metadata FIFO ownership or permissions")
        fd=os.open(fifo,os.O_WRONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
        try:
            payload=title.encode("utf-8")+b"\n"
            if os.write(fd,payload)!=len(payload):
                raise OSError("Short FIFO write")
        finally:
            os.close(fd)
    except OSError as exc:
        # Log once per failed callback without exposing station or stream secrets.
        import syslog
        update.syslog(syslog.LOG_WARNING, "GlassCoder metadata send failed: "+str(exc))


def main() -> int:
    if len(sys.argv)!=4:
        print("Usage: pypad_glasscoder.py RIV_HOST RIV_PORT CONFIG",file=sys.stderr)
        return 2
    receiver=pypad.Receiver()
    receiver.setConfigFile(sys.argv[3])
    receiver.setPadCallback(send_now_playing)
    receiver.start(sys.argv[1],int(sys.argv[2]))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
