#!/usr/bin/env bash
# Secure loopback listener request service. Never exposes ports to WAN.
set -Eeuo pipefail
umask 077
fail() { echo "ERROR: $*" >&2; exit 1; }
[[ "$EUID" -ne 0 ]] || fail 'Run as desktop studio user'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || fail 'Requires Ubuntu 26.04'
(($# >= 1)) || fail 'Usage: bash tools/install-requests.sh GROUP [GROUP...]'
groups=()
for group in "$@"; do
  [[ "$group" =~ ^[A-Za-z0-9_][A-Za-z0-9_-]{0,9}$ ]] || fail "Invalid group: $group"
  groups+=(--group "$group")
done
here="$(cd "$(dirname "$0")" && pwd -P)"
[[ -f "$here/rdrequests.py" ]] || fail 'Missing request API'
cfg="$HOME/.config/rivendell-complete"
state="$HOME/.local/state/rivendell-complete"
units="$HOME/.config/systemd/user"
install -d -m 0700 "$cfg" "$state" "$units" "$HOME/.local/bin"
[[ ! -e "$cfg/request-listener.token" && ! -e "$cfg/request-admin.token" ]] || fail 'Tokens already exist'
[[ ! -e "$units/rdcomplete-requests.service" ]] || fail 'Service already exists'
install -m 0755 "$here/rdrequests.py" "$HOME/.local/bin/rdcomplete-requests"
python3 - "$cfg" <<'PY'
import os,pathlib,secrets,sys
root=pathlib.Path(sys.argv[1])
for name in ("request-listener.token","request-admin.token"):
    fd=os.open(root/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"w",encoding="ascii") as out:
        out.write(secrets.token_urlsafe(48)+"\n")
PY
unit="$units/rdcomplete-requests.service"
{
  printf '%s\n' '[Unit]' 'Description=Rivendell Complete listener requests' 'After=network.target'
  printf '%s\n' '[Service]' 'Type=simple'
  printf 'ExecStart=%%h/.local/bin/rdcomplete-requests --database %%h/.local/state/rivendell-complete/requests.sqlite --catalog %%h/.local/state/rivendell-complete/request-catalog.json --listener-token-file %%h/.config/rivendell-complete/request-listener.token --admin-token-file %%h/.config/rivendell-complete/request-admin.token --listen 127.0.0.1 --port 8787'
  for arg in "${groups[@]}"; do printf ' %s' "$arg"; done
  printf '\n'
  printf '%s\n' 'Restart=on-failure' 'RestartSec=3' 'UMask=0077' 'NoNewPrivileges=true' 'PrivateTmp=true' 'ProtectSystem=strict' 'ProtectHome=read-only' 'ReadWritePaths=%h/.local/state/rivendell-complete' 'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6' 'CapabilityBoundingSet='
  printf '%s\n' '[Install]' 'WantedBy=default.target'
} > "$unit"
chmod 0600 "$unit"
systemctl --user daemon-reload
echo 'Installed credentials and service, NOT started.'
echo 'Export catalog to ~/.local/state/rivendell-complete/request-catalog.json'
echo 'Then run: systemctl --user enable --now rdcomplete-requests.service'
