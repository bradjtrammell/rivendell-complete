#!/usr/bin/env bash
# Rivendell Complete user-component staging after the native 4.5.0 installation.
# Runs only in the foreground, preserving the existing database and NAS music.
set -Eeuo pipefail
umask 077

say() { printf "[Rivendell Complete] %s\n" "$*"; }
fail() { printf "[Rivendell Complete] ERROR: %s\n" "$*" >&2; exit 1; }
usage() {
  cat <<'HELP'
Usage: bash tools/finish-complete.sh [--request-group EXISTING_GROUP] [--service EXISTING_SERVICE] [--no-packages]

Completes available user-level component staging on an already installed Ubuntu
26.04 Rivendell 4.5.0-1 workstation. Installs catalog, planning, request and
diagnostic utilities and existing desktop launchers. Installs local GlassCoder/
JACK packages unless --no-packages is specified. Does not build native packages,
overwrite Rivendell configuration, alter the database, start a public request
server or activate a stream. Existing station groups/services are required for
optional service staging; their names are never guessed.
HELP
}
GROUP=
SERVICE=
SKIP_PACKAGES=0
while (( $# )); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --no-packages) SKIP_PACKAGES=1; shift ;;
    --request-group) (( $# > 1 )) || fail "--request-group needs a value"; GROUP="$2"; shift 2 ;;
    --service) (( $# > 1 )) || fail "--service needs a value"; SERVICE="$2"; shift 2 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done
(( EUID != 0 )) || fail "Run as the regular desktop user, not root"
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || fail "Ubuntu 26.04 required"
[[ "$(dpkg --print-architecture)" == amd64 ]] || fail "amd64 required"
for value in "$GROUP" "$SERVICE"; do
  [[ -z "$value" || "$value" =~ ^[A-Za-z0-9_][A-Za-z0-9_-]{0,9}$ ]] || fail "Invalid station group/service name"
done
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
[[ -f "$ROOT/tools/install-station-utilities.sh" && -f "$ROOT/tools/install-streaming.sh" ]] || fail "Incomplete source checkout"
for package in rivendell rivendell-webapi; do
  status="$(dpkg-query -W -f='${Status} ${Version}' "$package" 2>/dev/null || :)"
  [[ "$status" == "install ok installed 4.5.0-1" ]] || fail "$package version 4.5.0-1 is not installed"
done
[[ -L /etc/rd.conf && -f /etc/rd.conf ]] || fail "Expected existing Rivendell config symlink is missing; not changing it"
for app in rdadmin rdairplay rdlibrary rdlogmanager rdlogedit rdpanel rdcatch rdcastmanager rddbmgr; do
  command -v "$app" >/dev/null || fail "Missing native application: $app"
done
say "Native Rivendell applications are installed; no native package will be rebuilt"

say "Installing existing catalog, scheduling, requests, imaging and diagnostic tools"
bash "$ROOT/tools/install-station-utilities.sh"

# The native package normally installs these desktop files system-wide. Stage
# an accessible per-user application launcher only when one does not exist.
# Preserve user-customized launchers and refuse symlink destinations.
DESKTOP="$HOME/.local/share/applications"
install -d -m 0755 "$DESKTOP"
installed_launchers=0
for name in rdadmin rdairplay rdlibrary rdlogmanager rdlogedit rdpanel rdcatch rdcartslots rdcastmanager rdmonitor rdlogin rdsoftkeys; do
  source_path="$ROOT/xdg/rivendell-$name.desktop"
  [[ -f "$source_path" ]] || fail "Missing supplied desktop launcher: $source_path"
  destination="$DESKTOP/rivendell-$name.desktop"
  [[ ! -L "$destination" ]] || fail "Refusing symlinked desktop launcher: $destination"
  if [[ -e "$destination" ]]; then
    say "Preserving existing launcher: $destination"
    continue
  fi
  # Only publish launchers for programs that are actually installed.
  if ! command -v "$name" >/dev/null; then
    say "No installed $name executable; skipping launcher"
    continue
  fi
  install -m 0644 "$source_path" "$destination"
  installed_launchers=$((installed_launchers+1))
done
say "Staged $installed_launchers new desktop launchers; log out and back in to refresh the application menu"

if [[ -n "$GROUP" || -n "$SERVICE" ]]; then
  sudo -v
  if [[ -n "$GROUP" ]]; then
    found="$(sudo -n mariadb -NBe "SELECT COUNT(*) FROM Rivendell.GROUPS WHERE NAME='$GROUP'" 2>/dev/null)" ||
      fail "Cannot read Rivendell groups; no service settings changed"
    [[ "$found" == 1 ]] || fail "Request group $GROUP does not exist in RDAdmin"
  fi
  if [[ -n "$SERVICE" ]]; then
    found="$(sudo -n mariadb -NBe "SELECT COUNT(*) FROM Rivendell.SERVICES WHERE NAME='$SERVICE'" 2>/dev/null)" ||
      fail "Cannot read Rivendell services; no service settings changed"
    [[ "$found" == 1 ]] || fail "Service $SERVICE does not exist in RDAdmin"
  fi
fi

if [[ -n "$GROUP" ]]; then
  if [[ -e "$HOME/.config/rivendell-complete/request-listener.token" || -e "$HOME/.config/rivendell-complete/request-admin.token" || -e "$HOME/.config/systemd/user/rdcomplete-requests.service" ]]; then
    say "Request service already provisioned; preserving credentials and service; no overwrite"
  else
    bash "$ROOT/tools/install-requests.sh" "$GROUP"
  fi
else
  say "Request API executable staged but listener service not provisioned: --request-group is needed"
fi
if [[ -n "$SERVICE" ]]; then
  if [[ -e "$HOME/.config/rivendell-complete/loggen.env" || -e "$HOME/.config/systemd/user/rdcomplete-loggen.timer" ]]; then
    say "Log generator already provisioned; preserving its configuration"
  else
    bash "$ROOT/tools/install-loggen.sh" "$SERVICE"
  fi
else
  say "Scheduling tools staged but automatic log timer not provisioned: --service is needed"
fi

if (( SKIP_PACKAGES == 1 )); then
  say "Skipping APT as requested; staging stream scripts and disabled units"
  bash "$ROOT/tools/install-streaming.sh" --skip-dependencies
else
  deps_ready=1
  for package in glasscoder jack-tools jackd2; do
    if [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || :)" != "install ok installed" ]]; then
      deps_ready=0
    fi
  done
  if (( deps_ready == 0 )) && command -v fuser >/dev/null 2>&1 &&
      sudo fuser -s /var/lib/dpkg/lock-frontend 2>/dev/null; then
    say "APT lock is held by another process. Leaving it alone; GlassCoder/JACK pending."
    say "Inspect with: ps -eo pid,ppid,etime,stat,args | grep -E '[a]pt-get|[d]pkg|[u]nattended-upgrade'"
    bash "$ROOT/tools/install-streaming.sh" --skip-dependencies
    say "All available user tools, desktop launchers, and stream scripts were staged before this blocker."
    exit 2
  fi
  say "Staging GlassCoder/JACK and stream service definitions (stream remains OFF)"
  bash "$ROOT/tools/install-streaming.sh" || fail "Streaming dependency staging failed; core/data unchanged"
fi

say "Verifying currently staged user executables"
for name in stationplan smartclock catalog external-media requests live-requests selftest loggen; do
  [[ -x "$HOME/.local/bin/rdcomplete-$name" ]] || fail "Missing staged rdcomplete-$name"
done
for name in stream metadata jack-route; do
  [[ -x "$HOME/.local/bin/rdcomplete-$name" ]] || fail "Missing staged rdcomplete-$name"
done
for unit in rdcomplete-stream.service rdcomplete-jack-route.service; do
  [[ -f "$HOME/.config/systemd/user/$unit" ]] || fail "Missing user service file: $unit"
done
say "COMPONENT STAGING FINISHED. No broadcast services, NAS sources, clocks, or remote streams were activated."
say "External NAS address, station service/groups, stream server and source credentials still require actual station configuration."
