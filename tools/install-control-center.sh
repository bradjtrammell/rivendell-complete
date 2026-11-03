#!/usr/bin/env bash
# Install the Rivendell Complete native operator console and root-owned NAS helper.
set -Eeuo pipefail
umask 077
SKIP_PACKAGES=0
if (( $# > 0 )); then
  if (( $# == 1 )) && [[ "$1" == --no-packages ]]; then
    SKIP_PACKAGES=1
  elif (( $# == 1 )) && [[ "$1" == --help ]]; then
    echo 'Usage: bash tools/install-control-center.sh [--no-packages]'
    exit 0
  else
    echo 'ERROR: Unexpected operator console installer options' >&2
    exit 2
  fi
fi
fail() { printf 'Rivendell Complete console: ERROR: %s\n' "$*" >&2; exit 1; }
(( EUID != 0 )) || fail 'Run as the desktop user'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || fail 'Requires Ubuntu 26.04'
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
for path in tools/rdcomplete_control.py tools/rdcomplete_root.py tools/setup-nas.sh \
            tools/rdexternal.py tools/rdcatalog.py tools/rdmounts.py tools/rdbrowse.py tools/rdsourcefolders.py tools/rdrequest_ops.py tools/rdrequests.py tools/rdlive.py tools/upgrade-request-portal.py xdg/rivendell-complete.desktop; do
  [[ -f "$ROOT/$path" && ! -L "$ROOT/$path" ]] || fail "Missing or symlinked source: $path"
done
if ! /usr/bin/python3 -c 'from PyQt5 import QtWidgets, QtCore, QtGui' 2>/dev/null ||
   ! command -v pkexec >/dev/null; then
  if (( SKIP_PACKAGES == 1 )); then
    fail 'Qt or pkexec missing: --no-packages forbids installing the GUI runtime'
  fi
  echo 'Installing the native Qt GUI runtime from Ubuntu 26.04 repositories'
  sudo -v
  sudo env DEBIAN_FRONTEND=noninteractive apt-get \
    -o DPkg::Lock::Timeout=300 install -y --no-install-recommends python3-pyqt5 pkexec || 
      fail 'Qt/Polkit dependencies are unavailable; no console installed'
fi
command -v pkexec >/dev/null || fail 'The polkit pkexec command is missing'
/usr/bin/python3 -c 'from PyQt5 import QtWidgets, QtCore, QtGui' || fail 'PyQt5 import failed'
/usr/bin/python3 -m py_compile "$ROOT/tools/rdcomplete_control.py" "$ROOT/tools/rdcomplete_root.py" "$ROOT/tools/rdbrowse.py" "$ROOT/tools/rdsourcefolders.py" "$ROOT/tools/rdrequest_ops.py"
if (( SKIP_PACKAGES == 0 )); then
  missing_tools=()
  command -v smbclient >/dev/null || missing_tools+=(smbclient)
  command -v showmount >/dev/null || missing_tools+=(nfs-common)
  if (( ${#missing_tools[@]} > 0 )); then
    sudo -v
    sudo env DEBIAN_FRONTEND=noninteractive apt-get \
      -o DPkg::Lock::Timeout=300 install -y --no-install-recommends "${missing_tools[@]}" ||
      fail 'Could not install NAS discovery dependencies'
  fi
fi
sudo -v
sudo install -d -o root -g root -m 0755 /usr/local/libexec/rivendell-complete
for name in setup-nas.sh rdexternal.py rdcatalog.py rdmounts.py \
            rdrequest_ops.py rdrequests.py rdlive.py; do
  sudo install -o root -g root -m 0755 "$ROOT/tools/$name" "/usr/local/libexec/rivendell-complete/$name"
done
sudo install -o root -g root -m 0755 "$ROOT/tools/rdcomplete_root.py" \
  /usr/local/libexec/rivendell-complete/rdcomplete_root.py
# Expose read-only mount inventory to the GUI without a root prompt.
sudo install -o root -g root -m 0755 "$ROOT/tools/rdmounts.py" \
  /usr/local/bin/rdcomplete-mounts
sudo install -o root -g root -m 0755 "$ROOT/tools/rdbrowse.py" \
  /usr/local/bin/rdcomplete-browse
sudo install -o root -g root -m 0755 "$ROOT/tools/rdsourcefolders.py" \
  /usr/local/bin/rdcomplete-source-folders
sudo install -o root -g root -m 0755 "$ROOT/tools/rdrequest_ops.py" \
  /usr/local/bin/rdcomplete-request-ops
sudo install -o root -g root -m 0755 "$ROOT/tools/rdcomplete_control.py" \
  /usr/local/bin/rdcomplete-control
# Upgrade only a previously generated service, retaining its original credentials.
if [[ -f "$HOME/.config/systemd/user/rdcomplete-requests.service" ]]; then
  /usr/bin/python3 "$ROOT/tools/upgrade-request-portal.py" ||
    fail 'Listener service was customized or unsafe; preserving it for inspection'
  systemctl --user daemon-reload || fail 'Could not reload user service definitions'
fi
sudo install -o root -g root -m 0644 "$ROOT/xdg/rivendell-complete.desktop" \
  /usr/share/applications/rivendell-complete.desktop
for name in /usr/local/bin/rdcomplete-control \
  /usr/local/libexec/rivendell-complete/rdcomplete_root.py \
  /usr/share/applications/rivendell-complete.desktop; do
  [[ "$(stat -c '%U:%G' "$name")" == root:root ]] || fail "Unsafe installed owner: $name"
done
echo 'Rivendell Complete Control Center installed in the desktop applications menu.'
echo 'Launch with: rdcomplete-control (from the Ubuntu desktop; not SSH).'
echo 'NAS import and broadcasting are not started automatically.'
