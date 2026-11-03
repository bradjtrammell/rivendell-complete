#!/usr/bin/env bash
# Guarded in-place native binary upgrade. The NAS catalog and original media
# are never copied, moved, converted, deleted, or rewritten.
set -Eeuo pipefail
umask 077

die() { printf 'Native upgrade ERROR: %s\n' "$*" >&2; exit 1; }
say() { printf 'Native upgrade: %s\n' "$*"; }

[[ "$(id -u)" -ne 0 ]] || die 'Run as the normal station desktop user'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || die 'Ubuntu 26.04 required'
[[ "$(dpkg --print-architecture)" == amd64 ]] || die 'AMD64 required'
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
[[ "$(git -C "$ROOT" branch --show-current)" == dev ]] || die 'Refusing non-dev branch'
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] ||
  die 'Source checkout has tracked modifications; commit or restore them first'
command -v dpkg-deb >/dev/null || die 'dpkg-deb missing'
command -v mysqldump >/dev/null || die 'mysqldump missing'
command -v objdump >/dev/null || die 'objdump missing'
command -v c++filt >/dev/null || die 'c++filt missing'
[[ -L /etc/rd.conf && "$(readlink /etc/rd.conf)" == /etc/rivendell.d/rd-default.conf ]] ||
  die 'Unexpected Rivendell configuration; refusing overwrite'
[[ "$(dpkg-query -W -f='${Status} ${Version}' rivendell 2>/dev/null || :)" == 'install ok installed 4.5.0-1' ]] ||
  die 'Rivendell package baseline mismatch'
[[ "$(dpkg-query -W -f='${Status} ${Version}' rivendell-webapi 2>/dev/null || :)" == 'install ok installed 4.5.0-1' ]] ||
  die 'Rivendell webapi package baseline mismatch'
[[ ! -e /etc/rivendell.d/rdcomplete-first-install ]] ||
  die 'First-install database marker still exists'
[[ -f /etc/rivendell.d/rd-default.conf ]] || die 'Station config missing'
[[ ! -L /etc/rivendell.d/rd-default.conf ]] || die 'Station config symlinked'
[[ ! -L /var/snd ]] || die 'Native audio store is a symlink'
[[ ! -L /mnt/radio-music ]] || die 'NAS root is a symlink'
if pgrep -x rdairplay >/dev/null; then
  die 'Close RDAirPlay before upgrading native CAE/library'
fi
if pgrep -x rdpanel >/dev/null; then
  die 'Close RDPanel before upgrading native runtime'
fi
[[ -f "$ROOT/rdairplay/rdairplay.cpp" ]] || die 'Source checkout incomplete'
grep -F 'Rivendell Complete - Listener Requests' "$ROOT/rdairplay/rdairplay.cpp" >/dev/null ||
  die 'Expected native Requests code missing'
grep -F 'playbackAudioFileName(name)' "$ROOT/cae/cae.cpp" >/dev/null ||
  die 'CAE source lacks direct NAS media lookup'
grep -F 'playbackAudioFileName(const QString &cutname)' "$ROOT/lib/rdconfig.cpp" >/dev/null ||
  die 'Native library lacks NAS resolver'
sudo -v

say 'Building current dev native packages (not using cached .deb files)'
bash "$ROOT/tools/install-ubuntu26.sh" --build-only --jobs 2
main="$ROOT/../rivendell_4.5.0-1_amd64.deb"
web="$ROOT/../rivendell-webapi_4.5.0-1_amd64.deb"
[[ -f "$main" && -f "$web" ]] || die 'Build did not create expected Debian packages'
[[ "$(dpkg-deb -f "$main" Package)" == rivendell ]] || die 'Main package identity mismatch'
[[ "$(dpkg-deb -f "$web" Package)" == rivendell-webapi ]] || die 'Web package identity mismatch'
for p in "$main" "$web"; do
  [[ "$(dpkg-deb -f "$p" Version)" == 4.5.0-1 ]] || die 'Version mismatch'
  [[ "$(dpkg-deb -f "$p" Architecture)" == amd64 ]] || die 'Architecture mismatch'
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
dpkg-deb -x "$main" "$work"
[[ -x "$work/usr/sbin/caed" ]] || die 'Native CAE missing from new package'
[[ -x "$work/usr/bin/rdairplay" ]] || die 'Native RDAirPlay missing from new package'
lib="$(find "$work/usr/lib" -maxdepth 1 -type f -name 'librd-*.so*' -print -quit)"
[[ -n "$lib" && -f "$lib" ]] || die 'Patched librd shared object missing'
objdump -T "$lib" | c++filt | grep -F 'RDConfig::playbackAudioFileName(QString const&) const' >/dev/null ||
  die 'Compiled shared library lacks direct NAS resolver'
strings "$work/usr/bin/rdairplay" | grep -F 'Rivendell Complete - Listener Requests' >/dev/null ||
  die 'Compiled native AirPlay lacks Requests panel'
[[ "$(sudo mariadb -NBe "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='Rivendell'")" =~ ^[1-9][0-9]*$ ]] ||
  die 'Station database is missing or empty'

say 'Creating private database and configuration recovery snapshots'
backup="/var/backups/rivendell-complete/native-$(date -u +%Y%m%dT%H%M%SZ)-$$"
sudo install -d -o root -g root -m 0700 "$backup"
sudo sh -c 'mysqldump --single-transaction --routines --triggers Rivendell > "$1/database.sql"' _ "$backup" ||
  die 'Database backup failed. Upgrade not started.'
sudo cp -p /etc/rivendell.d/rd-default.conf "$backup/rd-default.conf"
sudo sha256sum "$backup/database.sql" "$backup/rd-default.conf"
say "Recovery snapshots: $backup"

plan="$(sudo apt-get -s install --reinstall "$web" "$main")" ||
  die 'APT dependency simulation failed; no packages installed'
if grep -E '^(Remv |Purg )' <<<"$plan"; then
  die 'APT would remove packages; refusing native upgrade'
fi
say 'Reinstalling exact-version rebuilt native packages (maintainer hooks modify existing schema, never create)'
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y --reinstall --no-install-recommends "$web" "$main" ||
  die "Package upgrade failed. Preserve snapshots at $backup for recovery."
[[ -x /usr/sbin/caed && -x /usr/bin/rdairplay ]] ||
  die 'Required installed native binaries missing after upgrade'
cmp -s "$work/usr/sbin/caed" /usr/sbin/caed ||
  die "Installed CAE differs from rebuilt package; cannot claim patched playback"
cmp -s "$work/usr/bin/rdairplay" /usr/bin/rdairplay ||
  die "Installed RDAirPlay differs from rebuilt package"
lib_installed="/${lib#"$work/"}"
cmp -s "$lib" "$lib_installed" ||
  die "Installed shared audio library differs from rebuilt native resolver"
[[ -x /usr/bin/rdcomplete-control ]] ||
  die 'Control Center missing after upgrade'
sudo systemctl is-active --quiet rivendell ||
  die 'Rivendell did not restart; inspect journalctl -u rivendell'
say 'Updating Control Center and persistent NAS recovery without changing catalog'
bash "$ROOT/tools/install-control-center.sh" --no-packages ||
  die 'Native core updated, but console/NAS helper refresh failed; inspect this error'
say 'Refreshing separately launchable native Requests panel'
bash "$ROOT/tools/install-airplay-requests.sh" ||
  die 'Native core updated, but separate Requests launcher staging failed'
say 'Native runtime installed. NAS references remain in place; verify sample playback before going on air.'
say "Installed source revision: $(git -C "$ROOT" rev-parse HEAD)"
say "Recovery snapshots: $backup"
