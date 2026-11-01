#!/usr/bin/env python3
"""Read-only station readiness diagnostic; never modifies broadcast state."""
from __future__ import annotations

import argparse
import configparser
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request


class Check:
    def __init__(self):
        self.results=[]
    def add(self,name:str,passed:bool,detail:str,critical:bool=True):
        self.results.append({"name":name,"status":"pass" if passed else
                             ("fail" if critical else "warn"),"detail":detail})
    def command(self,program:str,arguments:list[str],timeout:int=8):
        if shutil.which(program) is None:
            return None
        try:
            return subprocess.run([program,*arguments],capture_output=True,
                                  text=True,timeout=timeout,check=False)
        except (OSError,subprocess.TimeoutExpired):
            return None
    def evaluate(self,config_file:Path,nas_override:Path|None=None):
        cfg=configparser.RawConfigParser()
        loaded=cfg.read(config_file)
        self.add("rivendell-config",bool(loaded),str(config_file))
        if not loaded:
            return
        release={}
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if "=" in line:
                    k,v=line.split("=",1);release[k]=v.strip('"')
        except OSError:
            pass
        self.add("ubuntu-26",release.get("ID")=="ubuntu" and
                 release.get("VERSION_ID")=="26.04",
                 f"{release.get('ID')} {release.get('VERSION_ID')}")
        for binary in ("rdairplay","rdlibrary","rdadmin","rdlogmanager",
                       "rdclilogedit","rddbmgr","ffprobe","glasscoder"):
            self.add("binary-"+binary,shutil.which(binary) is not None,
                     str(shutil.which(binary) or "missing"))
        mem_kb=0
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    mem_kb=int(line.split()[1]);break
        except (OSError,ValueError,IndexError):
            pass
        self.add("memory",mem_kb>=6*1024*1024,
                 f"{mem_kb//1024} MiB installed")
        try:
            free=shutil.disk_usage("/").free//(1024**3)
            self.add("boot-free-space",free>=8,f"{free} GiB available",
                     critical=False)
        except OSError as exc:
            self.add("boot-free-space",False,str(exc))
        for name in ("mariadb","rivendell"):
            p=self.command("systemctl",["is-active",name])
            self.add("service-"+name,p is not None and p.returncode==0,
                     (p.stdout.strip() if p else "unavailable"))
        nas=nas_override
        if nas is None:
            name=cfg.get("ExternalAudio","Root",fallback="")
            nas=Path(name) if name else None
        self.add("external-nas-configured",nas is not None,
                 str(nas or "missing"))
        if nas is not None:
            try:
                root=nas.resolve(strict=True)
                f=os.statvfs(root)
                readonly=bool(f.f_flag & os.ST_RDONLY)
                self.add("nas-readonly",readonly,str(root))
                mount=self.command("findmnt",["-rn","-o","SOURCE,FSTYPE,OPTIONS","-T",str(root)])
                detail=mount.stdout.strip() if mount and mount.returncode==0 else "mount missing"
                self.add("nas-mounted",bool(mount and mount.returncode==0
                                            and root!=Path("/")),detail)
                first=next((str(x.relative_to(root)) for x in root.rglob("*")
                            if x.is_file() and x.suffix.lower() in (".mp3",".wav",".ogg",".flac")),None)
                self.add("nas-audio-readable",bool(first),first or "no audio found")
            except (OSError,StopIteration) as exc:
                self.add("nas-readonly",False,str(exc))
        for name in ("rdairplay","jackd"):
            result=self.command("pgrep",["-x",name])
            self.add("running-"+name,result is not None and result.returncode==0,
                     "active" if result is not None and result.returncode==0 else "inactive",
                     critical=False)
        jack=self.command("jack_lsp",[],timeout=5)
        self.add("jack-audio-ports",bool(jack and jack.returncode==0 and jack.stdout.strip()),
                 "available" if jack and jack.returncode==0 else "not connected",
                 critical=False)
        stream=self.command("systemctl",["--user","is-active","rdcomplete-stream.service"])
        self.add("stream-encoder",bool(stream and stream.returncode==0),
                 stream.stdout.strip() if stream else "not installed",
                 critical=False)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8787/healthz",timeout=2) as res:
                ok=res.status==200
        except (urllib.error.URLError,OSError):
            ok=False
        self.add("request-service",ok,"loopback request API health",
                 critical=False)
    def exit_status(self,strict:bool)->int:
        if any(r["status"]=="fail" for r in self.results):
            return 1
        if strict and any(r["status"]=="warn" for r in self.results):
            return 2
        return 0


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=Path("/etc/rd.conf"))
    parser.add_argument("--nas",type=Path)
    parser.add_argument("--strict",action="store_true",
                        help="Warn conditions are also nonzero exit")
    parser.add_argument("--json",action="store_true")
    args=parser.parse_args(argv)
    c=Check()
    c.evaluate(args.config,args.nas)
    if args.json:
        print(json.dumps({
            "checked_at":datetime.now(timezone.utc).isoformat(),
            "checks":c.results},indent=2))
    else:
        for row in c.results:
            print(f"{row['status']:>4}  {row['name']:<28} {row['detail']}")
    return c.exit_status(args.strict)


if __name__=="__main__":
    raise SystemExit(main())
