#!/usr/bin/env python3
"""Keep explicit JACK stereo routes connected after service/audio restarts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


class RouteError(ValueError):
    pass


def run(args:list[str],timeout:int=5):
    return subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,
                          text=True,timeout=timeout,check=False)


def ports() -> dict[str,set[str]]:
    if shutil.which("jack_lsp") is None:
        raise RouteError("JACK utilities missing: install jack-tools")
    result=run(["jack_lsp","-p"])
    if result.returncode:
        raise RouteError("JACK server is not running")
    found={}
    current=None
    for line in result.stdout.splitlines():
        if not line.startswith((" ","\t")) and line:
            current=line.strip()
            found.setdefault(current,set())
        elif current is not None and line.strip().startswith("properties:"):
            found[current].update(x.strip().lower() for x in
                                  line.split(":",1)[1].split(","))
    return found


def validate(pairings:list[list[str]]) -> None:
    if not isinstance(pairings,list) or not 1<=len(pairings)<=32:
        raise RouteError("Provide 1-32 JACK port connections")
    seen=set()
    for pair in pairings:
        if not isinstance(pair,list) or len(pair)!=2:
            raise RouteError("Connection must be [output_port,input_port]")
        src,dst=pair
        if (not isinstance(src,str) or not isinstance(dst,str)
                or not 1<=len(src)<=255 or not 1<=len(dst)<=255
                or any(ord(c)<32 or ord(c)==127 for c in src+dst)
                or src==dst):
            raise RouteError("Unsafe JACK source or destination port")
        if (src,dst) in seen:
            raise RouteError("Duplicate JACK route")
        seen.add((src,dst))


def reconcile(pairings:list[list[str]], *, check_only:bool=False)->list[str]:
    validate(pairings)
    discovered=ports()
    problems=[]
    for src,dst in pairings:
        if src not in discovered or dst not in discovered:
            problems.append(f"Unavailable port: {src} -> {dst}")
            continue
        if "output" not in discovered[src] or "input" not in discovered[dst]:
            problems.append(f"Wrong port direction: {src} -> {dst}")
            continue
        if check_only:
            continue
        r=run(["jack_connect",src,dst])
        if r.returncode:
            # jack_connect returns failure for an existing connection;
            # verify the actual JACK graph instead of assuming success.
            connected=run(["jack_lsp","-c",src])
            if not (connected.returncode==0 and
                    dst in [x.strip() for x in connected.stdout.splitlines()[1:]]):
                problems.append(f"Cannot connect {src} -> {dst}: {r.stderr.strip()}")
    return problems


def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path,default=Path.home()/".config/rivendell-complete/jack-route.json")
    p.add_argument("--discover",action="store_true")
    p.add_argument("--check",action="store_true")
    p.add_argument("--once",action="store_true")
    p.add_argument("--interval",type=int,default=5)
    args=p.parse_args(argv)
    if args.discover:
        for name,properties in sorted(ports().items()):
            print(f"{name} [{','.join(sorted(properties))}]")
        return 0
    if not 2<=args.interval<=60:
        raise RouteError("Reconnect interval must be 2-60 seconds")
    config=json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(config,dict):
        raise RouteError("JACK config must be an object")
    routes=config.get("connections")
    validate(routes)
    last=[]
    while True:
        problems=reconcile(routes,check_only=args.check)
        if problems!=last:
            for item in problems:
                print("WARNING "+item,file=sys.stderr,flush=True)
            if not problems:
                print(f"JACK routes verified: {len(routes)}",flush=True)
            last=problems
        if args.once or args.check:
            return 1 if problems else 0
        time.sleep(args.interval)


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (RouteError,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        raise SystemExit(1)
