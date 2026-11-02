#!/usr/bin/env bash
# Install the Rivendell Complete native operator console and root-owned NAS helper.
set -Eeuo pipefail
umask 077
fail() { printf 'Rivendell Complete console: ERROR: %s\n' "$*" >&2; exit 1; }
(( EUID != 0 )) || fail 'Run as the desktop user'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || fail 'Requires Ubuntu 26.04'
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
for path in tools/rdcomplete_control.py tools/rdcomplete_root.py tools/setup-nas.sh \
            tools/rdexternal.py tools/rdcatalog.py xdg/rivendell-complete.desktop; do
  [[ -f "$ROOT/$path" && ! -L "$ROOT/$path" ]] || fail "Missing or symlinked source: $path"
done
if ! /usr/bin/python3 -c 'from PyQt5 import QtWidgets, QtCore, QtGui' 2>/dev/null; then
  echo 'Installing the native Qt GUI runtime from Ubuntu 26.04 repositories'
  sudo -v
  sudo env DEBIAN_FRONTEND=noninteractive apt-get \
    -o DPkg::Lock::Timeout=300 install -y --no-install-recommends python3-pyqt5 pkexec || 
      fail 'Qt/Polkit dependencies are unavailable; no console installed'
fi
command -v pkexec >/dev/null || fail 'The polkit pkexec command is missing'
/usr/bin/python3 -c 'from PyQt5 import QtWidgets, QtCore, QtGui' || fail 'PyQt5 import failed'
/usr/bin/python3 -m py_compile "$ROOT/tools/rdcomplete_control.py" "$ROOT/tools/rdcomplete_root.py"
sudo -v
sudo install -d -o root -g root -m 0755 /usr/local/libexec/rivendell-complete
for name in setup-nas.sh rdexternal.py rdcatalog.py; do
  sudo install -o root -g root -m 0755 "$ROOT/tools/$name" "/usr/local/libexec/rivendell-complete/$name"
done
sudo install -o root -g root -m 0755 "$ROOT/tools/rdcomplete_root.py" \
  /usr/local/libexec/rivendell-complete/rdcomplete_root.py
sudo install -o root -g root -m 0755 "$ROOT/tools/rdcomplete_control.py" \
  /usr/local/bin/rdcomplete-control
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
