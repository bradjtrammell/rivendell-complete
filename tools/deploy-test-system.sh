#!/usr/bin/env bash
# Rivendell Complete 5.0: guarded Ubuntu 26.04 test workstation deployment.
set -Eeuo pipefail
umask 027
fail(){ printf 'Rivendell Complete deployment: %s\n' "$*" >&2; exit 1; }
log(){ printf 'Rivendell Complete deployment: %s\n' "$*"; }
usage(){
  cat <<'HELP'
Usage: bash tools/deploy-test-system.sh [--check-only|--build-only|--install|--install-existing]
  [--jobs 1..4] [--nfs HOST:/EXPORT | --smb //HOST/SHARE]
  [--streaming] [--request-group RD_GROUP]

Default --check-only: static checks and Python regression suite; no system changes.
Install modes run syntax/compile checks, NOT integration or UDP-port tests.
--build-only: checks plus native Ubuntu 26.04 package build; no installation.
--install-existing: install validated existing .deb archives without compilation.
--install: checks, build, guarded fresh installation and optional components.
--nfs / --smb mounts an existing NAS source strictly read-only (never copies files).
--streaming installs encoder tools but DOES NOT start or configure an outgoing feed.
--request-group installs private request service but DOES NOT enable the service.
An installed test station is NOT broadcast-qualified. Configure RDAdmin, clocks,
audio, stream credentials, source paths and requests before any on-air testing.
HELP
}
mode=check
jobs=2
source_type=
source_path=
streaming=0
group=
while (($#)); do
  case "$1" in
    --check-only) mode=check; shift ;;
    --build-only) mode=build; shift ;;
    --install) mode=install; shift ;;
    --install-existing) mode=install_existing; shift ;;
    --jobs)
      (($# >= 2)) || fail 'Missing --jobs argument'
      jobs="$2"; shift 2 ;;
    --nfs|--smb)
      (($# >= 2)) || fail "Missing source for $1"
      [[ -z "$source_type" ]] || fail 'Exactly one NAS source allowed'
      source_type="$1"; source_path="$2"; shift 2 ;;
    --streaming) streaming=1; shift ;;
    --request-group)
      (($# >= 2)) || fail 'Missing request group'
      [[ -z "$group" ]] || fail 'Use one request-group during initial installation'
      group="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done
[[ "$jobs" =~ ^[1-4]$ ]] || fail 'Jobs must be 1..4'
[[ "$EUID" -ne 0 ]] || fail 'Run as desktop user, not root'
[[ -z "$group" || "$group" =~ ^[A-Za-z0-9_][A-Za-z0-9_-]{0,9}$ ]] ||
  fail 'Invalid request group'
if [[ "$mode" != install && "$mode" != install_existing ]]; then
  [[ -z "$source_type" && -z "$group" && "$streaming" -eq 0 ]] ||
    fail 'NAS, streaming and request installation require --install'
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
[[ -f "$ROOT/configure.ac" && -f "$ROOT/tools/install-ubuntu26.sh" ]] ||
  fail 'Run from the Rivendell Complete source checkout'
cd "$ROOT"
log 'Checking installer syntax and Python modules'
bash -n tools/setup-nas.sh tools/install-ubuntu26.sh tools/install-streaming.sh \
  tools/install-requests.sh tools/install-loggen.sh tools/install-station-utilities.sh tools/deploy-test-system.sh
python3 -m compileall -q tools tests
if [[ "$mode" == check ]]; then
  log 'Running the development regression suite (check-only; never blocks an installed station)'
  python3 -m unittest discover -s tests -p 'test_*.py' -v
  log 'Repository tests passed; no station installation performed'
  exit 0
fi
log 'Installer syntax and Python bytecode checks passed; skipping development tests during installation'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || fail 'Ubuntu 26.04 required'
[[ "$(dpkg --print-architecture)" == amd64 ]] || fail 'amd64 required'
if [[ "$mode" == build ]]; then
  bash tools/install-ubuntu26.sh --build-only --jobs "$jobs"
  exit 0
fi
log 'Installing guarded fresh workstation baseline'
if [[ "$mode" == install_existing ]]; then
  bash tools/install-ubuntu26.sh --install-existing --jobs "$jobs"
else
  bash tools/install-ubuntu26.sh --install --jobs "$jobs"
fi
if [[ -n "$source_type" ]]; then
  log 'Mounting original NAS share read-only'
  sudo bash tools/setup-nas.sh "$source_type" "$source_path"
fi
if [[ "$streaming" -eq 1 ]]; then
  log 'Installing stream utilities (outgoing stream remains OFF)'
  bash tools/install-streaming.sh
fi
if [[ -n "$group" ]]; then
  log 'Installing request service (service remains OFF)'
  bash tools/install-requests.sh "$group"
fi
log 'Staging catalog, scheduling, requests and diagnostics command-line tools'
bash tools/install-station-utilities.sh
log 'Installing native Qt station operator console'
bash tools/install-control-center.sh
log 'Compiling and staging enhanced native RDAirPlay Requests panel'
bash tools/install-airplay-requests.sh
log 'Test install staging complete; it is NOT air-qualified'
log 'Next: configure RDAdmin/service, NAS references, stream and JACK outputs'
log 'Diagnostics: python3 tools/rdselftest.py --strict --json'
