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
    say 'INSTALLATION COMPLETED; station setup and on-air verification still required.'
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
  say 'Compiled .deb files found; continuing installation without recompiling.'
  bash tools/deploy-test-system.sh --install-existing --streaming --jobs 2
else
  say 'Building native Rivendell packages, then installing.'
  bash tools/deploy-test-system.sh --install --streaming --jobs 2
fi

say 'Verifying native packages and programs'
dpkg-query -W rivendell rivendell-webapi
for app in rdadmin rdairplay rdlibrary rdlogmanager rddbmgr; do
  command -v "$app" || fail "Missing installed application: $app"
done
say 'Service state:'
systemctl --no-pager --full status mariadb rivendell || true
say 'Open RDAdmin on the graphical Ubuntu desktop after logging out and back in.'
