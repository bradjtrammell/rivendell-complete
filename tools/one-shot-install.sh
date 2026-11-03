#!/usr/bin/env bash
# Direct foreground Ubuntu 26.04 amd64 test-station installation.
# Do not source this script into an interactive shell.
set -Eeuo pipefail
umask 077

say() { printf '[Rivendell Complete] %s\n' "$*"; }
fail() { printf '[Rivendell Complete] ERROR: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'HELP'
Usage: bash tools/one-shot-install.sh

Run as the normal desktop user, never root. Runs in the foreground
of the current SSH terminal; no terminal multiplexers or background jobs.
Reuses valid local Debian packages when available, otherwise compiles from
source. Installs local MariaDB and stages the encoder (does not activate it).

Logs: ~/rivendell-install-logs/
Not approved for broadcasting until the station is commissioned and tested.
HELP
}
if (( $# > 0 )); then
  case "$1" in
    --help|-h) (( $# == 1 )) || fail 'Unexpected arguments'; usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
fi
[[ "$EUID" -ne 0 ]] || fail 'Log in as your regular desktop user, not root'
[[ -n "${HOME:-}" && -d "$HOME" ]] || fail 'HOME is not a valid directory'
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
[[ -f "$ROOT/configure.ac" && -f "$ROOT/tools/deploy-test-system.sh" ]] || fail 'Source checkout incomplete'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || fail 'Ubuntu 26.04 required'
[[ "$(dpkg --print-architecture)" == amd64 ]] || fail 'amd64 required'
[[ -w "$ROOT/.git" ]] || fail "Source checkout is not writable: $ROOT"

LOG_DIR="$HOME/rivendell-install-logs"
mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR"
LOG="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
touch "$LOG"
chmod 600 "$LOG"
exec > >(tee -a "$LOG") 2>&1
on_exit() {
  local rc=$?
  trap - EXIT
  if ((rc == 0)); then
    say 'INSTALLATION STAGING COMPLETED; on-air commissioning and feature verification still required.'
  else
    say "INSTALLATION FAILED (exit $rc). No automatic cleanup or destructive reset was performed."
  fi
  say "Installation log: $LOG"
  say 'The command has exited; your SSH shell remains available.'
}
trap on_exit EXIT

say "Starting as $(id -un); checkout: $ROOT"
say "Complete installation log: $LOG"
sudo -v
cd "$ROOT"
say 'Fetching dev changes without discarding the existing checkout'
git fetch origin dev
if [[ "$(git branch --show-current)" != dev ]]; then
  if git show-ref --verify --quiet refs/heads/dev; then
    git switch dev
  else
    git switch --track -c dev origin/dev
  fi
fi
git merge --ff-only origin/dev
say "Revision: $(git rev-parse --short HEAD)"

# Installation-state classification is performed by install-ubuntu26.sh:
# verified complete stations are kept, and only clearly marked interrupted
# first installs may be resumed. Unknown configurations are never overwritten.
if [[ -f "$ROOT/../rivendell_4.5.0-1_amd64.deb" && -f "$ROOT/../rivendell-webapi_4.5.0-1_amd64.deb" ]]; then
  say 'Compiled .deb files found; completing user tools without recompiling.'
  if ! bash tools/deploy-test-system.sh --install-existing --streaming --jobs 2; then
    fail 'Installation staging failed; see the first error above. Existing database and packages preserved.'
  fi
else
  say 'Building native Rivendell packages, then installing and staging user tools.'
  if ! bash tools/deploy-test-system.sh --install --streaming --jobs 2; then
    fail 'Installation failed; existing database and packages preserved.'
  fi
fi

say 'Building and staging native RDAirPlay Requests integration'
bash tools/install-airplay-requests.sh ||
  fail 'Enhanced Requests panel failed validation; original AirPlay remains installed and unchanged.'

say 'Verifying native packages and programs'
command -v rdcomplete-control || fail 'Rivendell Complete operator console is missing'
dpkg-query -W rivendell rivendell-webapi
for app in rdadmin rdairplay rdlibrary rdlogmanager rdlogedit rdpanel rdcatch rdcastmanager rddbmgr; do
  command -v "$app" || fail "Missing installed application: $app"
done
for tool in rdcomplete-stream rdcomplete-metadata rdcomplete-jack-route rdcomplete-stationplan rdcomplete-smartclock rdcomplete-catalog rdcomplete-external-media rdcomplete-requests rdcomplete-live-requests rdcomplete-selftest rdcomplete-loggen; do
  [[ -x "$HOME/.local/bin/$tool" ]] || fail "Missing staged station component: $tool"
  say "Staged tool: $HOME/.local/bin/$tool"
done
for unit in rdcomplete-stream.service rdcomplete-jack-route.service; do
  [[ -f "$HOME/.config/systemd/user/$unit" ]] || fail "Missing staged station unit: $unit"
done
say 'Services (informational; not a station readiness test):'
systemctl is-active mariadb rivendell || true
say 'Base applications and streaming utilities staged. Music library, station service, routes, credentials and scheduling still require commissioning.'
say 'Log out and back in before launching RDAdmin in the Ubuntu desktop.'
