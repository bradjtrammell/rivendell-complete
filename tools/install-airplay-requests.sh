#!/usr/bin/env bash
# Stage only a validated enhanced native AirPlay binary, never reinstall core.
set -Eeuo pipefail
umask 027
die() { printf 'Rivendell Complete RDAirPlay: ERROR: %s\n' "$*" >&2; exit 1; }
(( EUID != 0 )) || die 'Run as the desktop user'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || die 'Ubuntu 26.04 required'
[[ "$(dpkg --print-architecture)" == amd64 ]] || die 'AMD64 required'
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
[[ "$(git -C "$ROOT" branch --show-current)" == dev ]] || die 'Only the dev branch is allowed'
[[ -f "$ROOT/rdairplay/rdairplay.cpp" && ! -L "$ROOT/rdairplay/rdairplay.cpp" ]] ||
  die 'RDAirPlay source missing or symlinked'
grep -Fq 'Rivendell Complete - Listener Requests' "$ROOT/rdairplay/rdairplay.cpp" ||
  die 'Expected native listener request integration not found'
# A source-only Requests feature is not an installed feature. Recompile
# this target before staging so stale upstream binaries cannot pass.
[[ -f "$ROOT/rdairplay/Makefile" ]] ||
  die 'Configured native build tree missing. Build Rivendell packages first.'
command -v make >/dev/null || die 'make is required to compile RDAirPlay'
echo 'Compiling enhanced native RDAirPlay Requests panel'
make -C "$ROOT/rdairplay" -j2 rdairplay ||
  die 'RDAirPlay compilation failed; original player remains unchanged'
bin="$ROOT/rdairplay/.libs/rdairplay"
if [[ ! -x "$bin" ]]; then bin="$ROOT/rdairplay/rdairplay"; fi
[[ -f "$bin" && -x "$bin" && ! -L "$bin" ]] ||
  die 'Built native RDAirPlay executable not found; this installer does not compile'
[[ "$(stat -c %u "$bin")" == "$(id -u)" ]] ||
  die 'Built native executable not owned by current user'
[[ -x /usr/bin/rdairplay ]] || die 'Original Rivendell is missing'
dpkg-query -W -f='${Status} ${Version}\n' rivendell |
  grep -Fxq 'install ok installed 4.5.0-1' || die 'Unexpected native package baseline'
command -v readelf >/dev/null || die 'readelf required'
readelf -h "$bin" | grep -F 'ELF64' || die 'Not an ELF64 executable'
readelf -h "$bin" | grep -F 'Advanced Micro Devices X86-64' || die 'Not an AMD64 executable'
command -v strings >/dev/null || die 'strings required'
strings "$bin" | grep -F 'Rivendell Complete - Listener Requests' ||
  die 'Binary lacks the newly compiled listener request panel'
if ldd "$bin" | grep -Eq 'not found|=>[[:space:]]+not'; then
  die 'Native binary has unresolved runtime libraries'
fi
if pgrep -x rdairplay >/dev/null; then
  die 'Stop RDAirPlay before staging a separate enhanced executable'
fi
[[ ! -L /usr/local/libexec/rivendell-complete ]] ||
  die 'Control Center libexec path is a symlink'
sudo -v
sudo install -d -o root -g root -m 0755 /usr/local/libexec/rivendell-complete
target=/usr/local/libexec/rivendell-complete/rdairplay-requests
[[ ! -L "$target" ]] || die 'Refusing symlinked playback destination'
desktop=/usr/share/applications/rivendell-complete-airplay.desktop
[[ ! -L "$desktop" ]] || die 'Refusing symlinked desktop launcher'
sudo install -o root -g root -m 0755 "$bin" "$target"
sudo install -o root -g root -m 0644 \
  "$ROOT/xdg/rivendell-complete-airplay.desktop" "$desktop"
cmp -s "$bin" "$target" || die 'Staged playback binary differs from validated build'
echo 'Enhanced RDAirPlay staged separately; original /usr/bin/rdairplay and database unchanged.'
echo 'Launch Rivendell Complete - AirPlay from the desktop.'
