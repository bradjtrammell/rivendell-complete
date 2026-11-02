#!/usr/bin/env bash
# Fresh Ubuntu 26.04 amd64 test-station installation. Never source into SSH.
set -Eeuo pipefail
umask 077

say() { printf '[Rivendell Complete] %s\n' "$*"; }
fail() { printf '[Rivendell Complete] ERROR: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'HELP'
Usage: bash tools/one-shot-install.sh

Run as the normal desktop user, never root. Starts a persistent tmux session
with a visible sudo prompt, private installation log and unattended native
package build and local MariaDB installation. The encoder is installed but
not configured or activated. Not approved for broadcasting.

Reconnect: tmux attach -t rivendell-install
Logs:      ~/rivendell-install-logs/
HELP
}
if (( $# > 0 )); then
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --run) (( $# == 1 )) || fail 'Unexpected arguments' ;;
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

if (( $# == 0 )); then
  if ! command -v tmux >/dev/null 2>&1; then
    say 'Installing tmux for SSH-safe operation'
    sudo apt-get update
    sudo apt-get install -y tmux
  fi
  if [[ -n "${TMUX:-}" ]]; then
    bash "$ROOT/tools/one-shot-install.sh" --run
    exit $?
  fi
  SESSION=rivendell-install
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    say "Attaching to existing session $SESSION"
    tmux attach-session -t "$SESSION"
    exit $?
  fi
  tmux new-session -d -s "$SESSION" -n installation
  tmux set-window-option -t "$SESSION:0" remain-on-exit on
  printf -v command 'bash %q --run' "$ROOT/tools/one-shot-install.sh"
  tmux send-keys -t "$SESSION:0.0" "$command" Enter
  say "Installer launched; reconnect with: tmux attach -t $SESSION"
  tmux attach-session -t "$SESSION"
  exit $?
fi

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
  say 'You may detach this tmux window using Ctrl+B, then D.'
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

# Guarded fresh install only; existing configuration/database is never wiped.
if [[ -e /etc/rd.conf || -e /etc/rivendell.d/rd-default.conf ]]; then
  fail 'Rivendell configuration exists. Refusing an unsafe reinstallation.'
fi
if dpkg-query -W -f='${Status}' rivendell 2>/dev/null | grep -qx 'install ok installed'; then
  fail 'Rivendell already installed. Refusing to overwrite.'
fi

say 'Installing native Rivendell packages, MariaDB and streaming tools'
bash tools/deploy-test-system.sh --install --streaming --jobs 2

say 'Verifying native packages and programs'
dpkg-query -W rivendell rivendell-webapi
for app in rdadmin rdairplay rdlibrary rdlogmanager rddbmgr; do
  command -v "$app" || fail "Missing installed application: $app"
done
say 'Service state:'
systemctl --no-pager --full status mariadb rivendell || true
say 'Open RDAdmin on the graphical Ubuntu desktop after logging out and back in.'
