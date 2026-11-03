#!/usr/bin/env bash
# Transactional native RDAirPlay + CAE + shared resolver upgrade.
# Never dpkg-installs Rivendell or invokes database upgrade hooks.
set -Eeuo pipefail
umask 077
say() { printf '[Rivendell Complete native] %s\n' "$*"; }
fail() { printf '[Rivendell Complete native] ERROR: %s\n' "$*" >&2; exit 1; }
(( EUID != 0 )) || fail 'Run as radiouser, never root'
[[ "$(id -un)" == radiouser && "$(hostname -s)" == rivendell ]] ||
  fail 'Requires radiouser on the rivendell workstation'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || fail 'Ubuntu 26.04 required'
[[ "$(dpkg --print-architecture)" == amd64 ]] || fail 'AMD64 required'
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
[[ "$(git branch --show-current)" == dev ]] || fail 'Expected dev branch'
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/dev)" ]] ||
  fail 'Local checkout must match origin/dev'
[[ -x /usr/sbin/caed && -x /usr/bin/rdairplay ]] || fail 'Native Rivendell missing'
dpkg-query -W -f='${Status} ${Version}\n' rivendell |
  grep -Fxq 'install ok installed 4.5.0-1' ||
  fail 'Unexpected native package baseline'
if pgrep -x rdairplay >/dev/null; then
  fail 'Close RDAirPlay on the desktop before upgrading its native playback engine'
fi
[[ -f /etc/rd.conf && -d /var/snd ]] || fail 'Rivendell configuration/audio directory missing'
for command in make gcc g++ readelf ldconfig strings nm cmp sha256sum sudo; do
  command -v "$command" >/dev/null || fail "Missing build prerequisite: $command"
done
sudo -v || fail 'Privilege check failed'
say 'Building matched native engine and RDAirPlay; no installed files changed yet'
if [[ ! -x ./configure || ! -f Makefile ]]; then
  command -v autoreconf >/dev/null || fail 'Autoconf/Automake dependencies missing'
  ./autogen.sh
  ./configure --prefix=/usr --disable-docbook \
    MUSICBRAINZ_LIBS="-ldiscid -lmusicbrainz5cc -lcoverartcc"
fi
make -j2
gui=rdairplay/.libs/rdairplay
[[ -f "$gui" && -x "$gui" ]] || gui=rdairplay/rdairplay
cae=cae/.libs/caed
[[ -f "$cae" && -x "$cae" ]] || cae=cae/caed
lib=lib/.libs/librd-4.5.0.so
destlib=/usr/lib/librd-4.5.0.so
for p in "$gui" "$cae" "$lib" /usr/bin/rdairplay /usr/sbin/caed "$destlib"; do
  [[ -f "$p" && ! -L "$p" ]] || fail "Missing plain ELF file: $p"
done
for p in "$gui" "$cae" "$lib"; do
  readelf -h "$p" | grep -Fq 'ELF64' || fail "Not ELF64: $p"
  if ldd "$p" | grep -E 'not found|=>[[:space:]]+not'; then
    fail "Unresolved native runtime dependency in $p"
  fi
done
readelf -d "$lib" | grep -Fq '[librd-4.5.0.so]' ||
  fail 'New native shared library SONAME mismatch'
readelf -d "$destlib" | grep -Fq '[librd-4.5.0.so]' ||
  fail 'Existing native shared library SONAME mismatch'
strings "$gui" | grep -F 'Rivendell Complete - Listener Requests' >/dev/null ||
  fail 'Requests panel not compiled into RDAirPlay'
nm -D "$lib" | grep -F playbackAudioFileName >/dev/null ||
  fail 'External NAS playback resolver not compiled into native library'
was_active=0
if systemctl is-active --quiet rivendell; then was_active=1; fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
short="$(git rev-parse --short=12 HEAD)"
backup="/var/lib/rivendell-complete/native-backups/$stamp-$short"
sudo install -d -o root -g root -m 0700 "$backup"
for file in /usr/bin/rdairplay /usr/sbin/caed "$destlib"; do
  sudo cp -a -- "$file" "$backup/$(basename "$file")"
  sudo cmp -s "$file" "$backup/$(basename "$file")" ||
    fail "Native recovery backup verification failed: $file"
done
changed=0
rollback() {
  local rc=$?
  trap - EXIT ERR INT TERM
  if (( rc != 0 && changed == 1 )); then
    say 'FAILURE: restoring all three original native files'
    sudo systemctl stop rivendell >/dev/null 2>&1 || true
    sudo cp -a -- "$backup/rdairplay" /usr/bin/rdairplay
    sudo cp -a -- "$backup/caed" /usr/sbin/caed
    sudo cp -a -- "$backup/librd-4.5.0.so" "$destlib"
    sudo ldconfig
    if (( was_active == 1 )); then sudo systemctl start rivendell || true; fi
    printf 'Native recovery folder: %s\n' "$backup" >&2
  fi
}
trap rollback EXIT
say 'Installing matched library + CAE + RDAirPlay without touching the database'
changed=1
sudo systemctl stop rivendell
sudo install -o root -g root -m 0755 "$lib" "$destlib"
sudo install -o root -g root -m 0755 "$cae" /usr/sbin/caed
sudo install -o root -g root -m 0755 "$gui" /usr/bin/rdairplay
sudo ldconfig
sudo cmp -s "$lib" "$destlib" || fail 'Native library copy mismatch'
sudo cmp -s "$cae" /usr/sbin/caed || fail 'CAE copy mismatch'
sudo cmp -s "$gui" /usr/bin/rdairplay || fail 'RDAirPlay copy mismatch'
if (( was_active == 1 )); then
  sudo systemctl start rivendell
  sudo systemctl is-active --quiet rivendell ||
    fail 'Rivendell failed to restart; original binaries will be restored'
  pgrep -x caed >/dev/null ||
    fail 'New CAE did not start; restoring prior binaries'
fi
changed=0
trap - EXIT
say "Installed native Requests panel and external audio resolver at revision $short"
say "Reversible backups: $backup"
say 'No native package postinst, database migration or music deletion ran.'
