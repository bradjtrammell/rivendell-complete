#!/usr/bin/env bash
# Rivendell Complete 4.5.0: native Ubuntu 26.04 x86_64 build and fresh install.
set -Eeuo pipefail
umask 027

MODE=build
JOBS=2
fail() { printf '[RivendellComplete] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[RivendellComplete] %s\n' "$*"; }
usage() {
  cat <<'HELP'
Usage: ./tools/install-ubuntu26.sh [--build-only|--install] [--jobs 1..4]
 --build-only  Build native Ubuntu 26.04 .deb package (default)
 --install     Install on a FRESH standalone Ubuntu Desktop computer.
               Never uses an existing NAS music share as cart storage.
HELP
}
while (($#)); do
  case "$1" in
    --build-only) MODE=build; shift ;;
    --install) MODE=install; shift ;;
    --jobs) (($# > 1)) || fail 'Missing jobs'; JOBS="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done
[[ "$JOBS" =~ ^[1-4]$ ]] || fail '--jobs must be 1 through 4'
[[ "$EUID" -ne 0 ]] || fail 'Run as normal desktop user, not root'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || fail 'Requires Ubuntu 26.04'
[[ "$(dpkg --print-architecture)" == amd64 ]] || fail 'Requires x86_64/amd64'
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
[[ -e "$ROOT/autogen.sh" && -e "$ROOT/configure.ac" ]] || fail 'Must run from fork checkout'
[[ "$(cat "$ROOT/versions/PACKAGE_VERSION")" == 4.5.0 ]] || fail 'Expected Rivendell 4.5.0 source'
[[ "$ROOT" != / ]] || fail 'Unsafe source directory'
if [[ "$MODE" == install ]]; then
  [[ ! -e /etc/rd.conf && ! -e /etc/rivendell.d/rd-default.conf ]] || fail 'Existing Rivendell configuration found'
  if dpkg -s rivendell 2>/dev/null | grep -q '^Status: install ok installed'; then fail 'Already installed'; fi
  if mountpoint -q /var/snd; then fail '/var/snd is mounted; never point it at an existing music library'; fi
  [[ ! -e /var/snd || -z "$(find /var/snd -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail '/var/snd already has data'
fi
FREE_KB="$(df -Pk "$ROOT" | awk 'END {print $4}')"
((FREE_KB >= 10*1024*1024)) || fail '10 GiB free build space required'
sudo -v
log 'Enabling native Ubuntu 26.04 Universe (NO mixed Ubuntu repositories)'
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends software-properties-common
sudo add-apt-repository -y universe
sudo apt-get update

# Plain whitespace-separated APT list contains only fixed package literals.
PACKAGES='build-essential autoconf automake autoconf-archive autotools-dev libtool
pkgconf debhelper dh-autoreconf devscripts fakeroot dpkg-dev ca-certificates
git python3 python3-pycurl python3-pymysql python3-mysqldb python3-serial
python3-requests libexpat1-dev libid3-3.8.3-dev libcurl4-gnutls-dev libcoverart-dev
libdiscid-dev libmusicbrainz5-dev libcdparanoia-dev libsndfile1-dev
libpam0g-dev libvorbis-dev libsamplerate0-dev qtbase5-dev qttools5-dev-tools
libqt5sql5-mysql qtwebengine5-dev libsoundtouch-dev libjack-jackd2-dev
libasound2-dev libflac-dev libflac++-dev libmp3lame-dev libmad0-dev
libtwolame-dev libssl-dev libtag1-dev libmagick++-7.q16-dev
libltdl-dev rsync apache2 rsyslog mariadb-client
docbook5-xml libxml2-utils docbook-xsl-ns xsltproc fop icedax
qttranslations5-l10n ffmpeg openssl'
missing=()
while IFS= read -r p; do
  [[ -z "$p" ]] && continue
  candidate="$(apt-cache policy "$p" | awk '/Candidate:/ {print $2;exit}')"
  if [[ -z "$candidate" || "$candidate" == '(none)' ]]; then
    missing+=("$p")
  fi
done < <(printf '%s\n' "$PACKAGES" | tr ' ' '\n')
if (("${#missing[@]}" > 0)); then
  printf '[RivendellComplete] Unavailable native Ubuntu 26.04 packages:\n' >&2
  printf '  %s\n' "${missing[@]}" >&2
  fail 'Dependency preflight failed; no cross-release repositories will be used'
fi
# Intentional word splitting of a trusted literal package list.
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $PACKAGES
log 'Compiling patched QtWebEngine / ImageMagick 7 Rivendell'
cd "$ROOT"
./autogen.sh
export DEB_BUILD_OPTIONS="parallel=$JOBS"
export DEBUILD_MAKE_ARGS="-j$JOBS"
dpkg-buildpackage --build=binary --no-sign
PKG="$ROOT/../rivendell_4.5.0-1_amd64.deb"
[[ -f "$PKG" ]] || fail "Missing expected .deb: $PKG"
dpkg-deb -f "$PKG" Package Version Architecture
if [[ "$MODE" == build ]]; then
  log "Built $PKG. No Rivendell database/application installed."
  exit 0
fi

sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends mariadb-server
sudo systemctl enable --now mariadb
SCHEMA="$(sudo mariadb -NBe "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='Rivendell'")"
[[ -z "$SCHEMA" ]] || fail 'Existing Rivendell DB detected; refusing overwrite'
for account in rivendell pypad; do
  getent group "$account" >/dev/null || sudo groupadd --system "$account"
  id -u "$account" >/dev/null 2>&1 || sudo useradd --system --gid "$account" --shell /usr/sbin/nologin --home-dir /nonexistent "$account"
done
DB_SECRET="$(openssl rand -hex 32)"
SERVICE_SECRET="$(openssl rand -hex 32)"
[[ -n "$DB_SECRET" && -n "$SERVICE_SECRET" ]] || fail 'Secure random generation failed'
sudo mariadb <<SQL
CREATE DATABASE \`Rivendell\` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE USER IF NOT EXISTS 'rduser'@'localhost' IDENTIFIED BY '$DB_SECRET';
ALTER USER 'rduser'@'localhost' IDENTIFIED BY '$DB_SECRET';
GRANT ALL PRIVILEGES ON \`Rivendell\`.* TO 'rduser'@'localhost';
SQL
sudo install -d -o root -g rivendell -m 0750 /etc/rivendell.d
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
RD_DB_SECRET="$DB_SECRET" RD_SERVICE_SECRET="$SERVICE_SECRET" python3 - "$ROOT/conf/rd.conf-sample" "$TMP" <<'PY'
import os, re, sys
from pathlib import Path
s = Path(sys.argv[1]).read_text()
for section, name in (("Identity", "RD_SERVICE_SECRET"), ("mySQL", "RD_DB_SECRET")):
    m = re.search(r"(?ms)^\[" + re.escape(section) + r"\]\n(.*?)(?=^\[|\Z)", s)
    if m is None:
        raise SystemExit("Configuration section missing: " + section)
    body, n = re.subn(r"(?m)^Password=.*$", lambda _: "Password=" + os.environ[name], m.group(1))
    if n != 1:
        raise SystemExit("Unexpected upstream password configuration")
    s = s[:m.start(1)] + body + s[m.end(1):]
s = s.replace(";Engine=MyISAM", "Engine=InnoDB")
Path(sys.argv[2]).write_text(s)
PY
sudo install -o root -g rivendell -m 0640 "$TMP" /etc/rivendell.d/rd-default.conf
sudo ln -s /etc/rivendell.d/rd-default.conf /etc/rd.conf
sudo install -o root -g root -m 0600 /dev/null /etc/rivendell.d/rdcomplete-first-install
unset DB_SECRET SERVICE_SECRET
sudo usermod -aG rivendell "$(id -un)"
PLAN="$(sudo apt-get -s install "$PKG")" || fail 'Package transaction not satisfiable'
if grep -q '^Remv ' <<<"$PLAN"; then
  printf '%s\n' "$PLAN" >&2
  fail 'Refusing transaction that would remove installed packages'
fi
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$PKG"
for exe in rdadmin rdairplay rdlibrary rdlogmanager rdimport rddbmgr; do
  command -v "$exe" >/dev/null || fail "Installed executable missing: $exe"
done
log 'Installed application/database; NOT BROADCAST-QUALIFIED.'
log 'Log out/in, configure audio and service in RDAdmin, mount NAS read-only.'
log 'Then add [ExternalAudio] Root and References to /etc/rd.conf and index with rdexternal.py.'
