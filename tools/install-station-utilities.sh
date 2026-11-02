#!/usr/bin/env bash
# Install existing Rivendell Complete CLI utilities without starting station services.
set -Eeuo pipefail
umask 077
fail() { printf 'Rivendell Complete tools: ERROR: %s\n' "$*" >&2; exit 1; }
say() { printf 'Rivendell Complete tools: %s\n' "$*"; }
if [[ "${1:-}" == --help && $# -eq 1 ]]; then
  echo 'Usage: bash tools/install-station-utilities.sh'
  echo 'Stage CLI tools only; does not configure or start a station.'
  exit 0
fi
(( $# == 0 )) || fail 'No arguments expected'
(( EUID != 0 )) || fail 'Run as the desktop user, not root'
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
BIN="$HOME/.local/bin"
[[ -f "$ROOT/tools/rdstationplan.py" && -f "$ROOT/tools/rdrequests.py" ]] || fail 'Incomplete source checkout'
install -d -m 0700 "$BIN"
modules=(rdcatalog rdexternal rdsmartclock rdstationplan rdrequests rdlive rdselftest rdloggen rdsweepers rdmetadata rdjackroute rdstream pypad_glasscoder)
for module in "${modules[@]}"; do
  source_path="$ROOT/tools/$module.py"
  [[ -f "$source_path" ]] || fail "Missing utility source: $source_path"
  python3 -m py_compile "$source_path" || fail "Python syntax failed: $module"
  install -m 0755 "$source_path" "$BIN/$module.py"
done
for mapping in 'rdstationplan:stationplan' 'rdsmartclock:smartclock' 'rdcatalog:catalog' 'rdexternal:external-media' 'rdrequests:requests' 'rdlive:live-requests' 'rdselftest:selftest' 'rdloggen:loggen'; do
  module="${mapping%%:*}"
  name="${mapping#*:}"
  install -m 0755 "$ROOT/tools/$module.py" "$BIN/rdcomplete-$name"
  say "Staged $BIN/rdcomplete-$name"
done
say 'Command-line tools staged; live configurations, public ports, and station playout remain unchanged.'
