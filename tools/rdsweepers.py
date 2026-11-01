#!/usr/bin/env python3
"""Conservative Rivendell sound-panel sweeper overlay on known vocal intros.

Runs as a PyPAD receiver. Requires separate configured SoundPanel channel,
connected to same JACK output bus as main log. No song file is modified.
"""
from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import threading
import syslog
from typing import Any

RML_HOST="127.0.0.1"
RML_NOECHO_PORT=5859
PANEL="S50"
COLUMN=1
ROW=1


class SweeperError(ValueError):
    pass


def validate_catalog(data: dict) -> tuple[dict[int,int],list[tuple[int,int]]]:
    if not isinstance(data,dict):
        raise SweeperError("Sweepers configuration must be an object")
    raw=data.get("vocal_intros_ms",{})
    media=data.get("sweepers",[])
    if not isinstance(raw,dict) or not isinstance(media,list):
        raise SweeperError("Expected vocal_intros_ms object and sweepers list")
    intros={}
    for key,value in raw.items():
        try:
            cart=int(key)
        except (TypeError,ValueError) as exc:
            raise SweeperError("Invalid intro cart") from exc
        if type(value) is not int or not 0<=value<=120000 or not 1<=cart<=999999:
            raise SweeperError("Invalid intro marker")
        intros[cart]=value
    sweepers=[]
    for entry in media:
        cart=entry.get("cart") if isinstance(entry,dict) else None
        duration=entry.get("duration_ms") if isinstance(entry,dict) else None
        if type(cart) is not int or type(duration) is not int or not 1<=cart<=999999 or not 500<=duration<=60000:
            raise SweeperError("Invalid sweeper cart/duration")
        sweepers.append((cart,duration))
    return intros,sweepers


def pick_sweeper(song_cart: int, state: int, every: int,
                 intro: dict[int,int], sweepers: list[tuple[int,int]],
                 delay_ms: int=500, headroom_ms: int=800) -> int | None:
    if not 1<=every<=30 or not 0<=delay_ms<=10000 or not 0<=headroom_ms<=5000:
        raise SweeperError("Invalid overlay timing limits")
    if state%every:
        return None
    safe_intro=intro.get(song_cart,0)-delay_ms-headroom_ms
    suitable=[cart for cart,duration in sweepers if duration<=safe_intro]
    if not suitable:
        return None
    return suitable[(state//every-1)%len(suitable)]


def rml_commands(cart: int) -> tuple[bytes,bytes]:
    if type(cart) is not int or not 1<=cart<=999999:
        raise SweeperError("Invalid sweeper cart")
    # Panel S50 is reserved for automation and MUST be routed to same mix bus
    # as primary log; no main-log insertions or song cuts.
    return (f"PE {PANEL} {COLUMN} {ROW} {cart}!".encode("ascii"),
            f"PP {PANEL} {COLUMN} {ROW}!".encode("ascii"))


class SweeperBridge:
    def __init__(self, catalogue: Path, every: int=4, delay_ms: int=500):
        self.catalogue=catalogue
        self.every=every
        self.delay_ms=delay_ms
        self.sequence=0
        self.lock=threading.Lock()
        self.timer:threading.Timer|None=None

    def cancel(self) -> None:
        """Cancel a pending overlay if a legal ID, spot, or stop replaces music."""
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
                self.timer=None

    def on_song(self, cart: int) -> int|None:
        # Song starts must be triggered by PyPAD TYPE_NOW, not wall clock.
        with self.lock:
            self.sequence+=1
            if self.timer is not None:
                self.timer.cancel()
                self.timer=None
            raw=json.loads(self.catalogue.read_text(encoding="utf-8"))
            intros,sweepers=validate_catalog(raw)
            choice=pick_sweeper(cart,self.sequence,self.every,
                                intros,sweepers,self.delay_ms)
            if choice is None:
                return None
            timer=threading.Timer(self.delay_ms/1000,self.play,(choice,))
            timer.daemon=True
            timer.start()
            self.timer=timer
            return choice

    @staticmethod
    def play(cart:int)->None:
        commands=rml_commands(cart)
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                for command in commands:
                    if sock.sendto(command,(RML_HOST,RML_NOECHO_PORT))!=len(command):
                        raise SweeperError("Short RML datagram")
        except OSError as exc:
            syslog.syslog(syslog.LOG_WARNING,"Rivendell sweeper RML send failed: "+str(exc))


def main()->int:
    if len(sys.argv)!=4:
        print("Usage: rdsweepers.py RIV_HOST RIV_PORT PYPAD_CONFIG",file=sys.stderr)
        return 2
    try:
        from rivendellaudio import pypad
    except ModuleNotFoundError:
        import pypad
    import configparser
    parser=configparser.RawConfigParser()
    if not parser.read(sys.argv[3]):
        raise SweeperError("Cannot read PyPAD configuration")
    section="Sweepers"
    path=Path(parser.get(section,"Catalog"))
    every=parser.getint(section,"Every",fallback=4)
    delay=parser.getint(section,"DelayMs",fallback=500)
    bridge=SweeperBridge(path,every,delay)
    def on_pad(update):
        if not update.hasPadType(pypad.TYPE_NOW):
            return
        if not update.shouldBeProcessed(section):
            bridge.cancel()
            return
        try:
            cart=int(update.resolvePadFields("%n",pypad.ESCAPE_NONE))
            bridge.on_song(cart)
        except (OSError,ValueError,SweeperError,json.JSONDecodeError) as exc:
            update.syslog(syslog.LOG_WARNING,"Invalid sweeper update: "+str(exc))
    receiver=pypad.Receiver()
    receiver.setConfigFile(sys.argv[3])
    receiver.setPadCallback(on_pad)
    receiver.start(sys.argv[1],int(sys.argv[2]))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (SweeperError,OSError,ValueError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        raise SystemExit(1)
