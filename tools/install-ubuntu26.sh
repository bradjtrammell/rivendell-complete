#!/usr/bin/env bash
# Rivendell Complete 4.5.0: native Ubuntu 26.04 x86_64 build and fresh install.
set -Eeuo pipefail
umask 027
trap 'rc=$?; printf "[RivendellComplete] ERROR: Command failed at line %s (exit %s): %s\n" "$LINENO" "$rc" "$BASH_COMMAND" >&2' ERR

MODE=build
REUSE_PACKAGES=0
JOBS=2
fail() { printf '[RivendellComplete] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[RivendellComplete] %s\n' "$*"; }
usage() {
  cat <<'HELP'
Usage: ./tools/install-ubuntu26.sh [--build-only|--install|--install-existing] [--jobs 1..4]
 --build-only  Build native Ubuntu 26.04 .deb package (default)
 --install     Build and install on a FRESH Ubuntu Desktop computer.
 --install-existing  Reuse validated local .deb packages; skip compilation.
               Never uses an existing NAS music share as cart storage.
HELP
}
while (($#)); do
  case "$1" in
    --build-only) MODE=build; shift ;;
    --install) MODE=install; shift ;;
    --install-existing) MODE=install; REUSE_PACKAGES=1; shift ;;
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
  if mountpoint -q /var/snd; then fail '/var/snd is mounted; never point it at an existing music library'; fi
  # A failed package installation may already have created /etc/rd.conf.
  # Keep it untouched until the recovery-state check below can inspect it.
  if [[ ! -e /etc/rd.conf && ! -L /etc/rd.conf &&
        ! -e /etc/rivendell.d/rd-default.conf ]]; then
    [[ ! -e /var/snd || -z "$(find /var/snd -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
      fail '/var/snd already has data; refusing fresh installation'
  fi
fi
if (( REUSE_PACKAGES == 0 )); then
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
log 'Checking native Ubuntu 26.04 dependency candidates'
while IFS= read -r p; do
  if [[ -z "$p" ]]; then
    continue
  fi
  candidate="$(apt-cache policy "$p" | awk '/Candidate:/ {if (!found) {print $2; found=1}}')"
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
else
  log 'Existing packages detected: skipping native build'
fi
PKG="$ROOT/../rivendell_4.5.0-1_amd64.deb"
PKG_WEB="$ROOT/../rivendell-webapi_4.5.0-1_amd64.deb"
[[ -f "$PKG" ]] || fail "Missing Rivendell main .deb: $PKG"
[[ -f "$PKG_WEB" ]] || fail "Missing required web API runtime .deb: $PKG_WEB"
for package in "$PKG" "$PKG_WEB"; do
  dpkg-deb --info "$package" >/dev/null || fail "Invalid package archive: $package"
  dpkg-deb --contents "$package" >/dev/null || fail "Unreadable package archive: $package"
  dpkg-deb -f "$package" Package Version Architecture
  [[ "$(dpkg-deb -f "$package" Architecture)" == amd64 ]] || fail "Wrong architecture: $package"
  [[ "$(dpkg-deb -f "$package" Version)" == 4.5.0-1 ]] || fail "Wrong version: $package"
done
dpkg-deb --contents "$PKG" | grep '/usr/bin/rdairplay
  fail 'Main package is missing RDAirPlay'
[[ "$(dpkg-deb -f "$PKG" Package)" == rivendell ]] || fail 'Wrong main package name'
[[ "$(dpkg-deb -f "$PKG_WEB" Package)" == rivendell-webapi ]] || fail 'Wrong webapi package name'
if [[ "$MODE" == build ]]; then
  log "Built $PKG. No Rivendell database/application installed."
  exit 0
fi

log 'Reauthenticating sudo before package installation; long builds expire sudo timestamps'
sudo -v || fail 'sudo authentication failed; compiled .deb files remain intact'

# Classify previous installation state WITHOUT changing existing files.
# A fresh install has no configuration, database or installed packages.
# A resumable install must have OUR marker, OUR exact config symlink and
# an existing but EMPTY schema, so postinst --create cannot overwrite tables.
# A complete install must have the expected packages and nonempty schema.
# Any other state is deliberately left untouched for manual inspection.
RESUME_STAGED=0
if [[ "$MODE" == install ]]; then
  rd_conf=/etc/rd.conf
  rd_default=/etc/rivendell.d/rd-default.conf
  rd_marker=/etc/rivendell.d/rdcomplete-first-install
  has_conf=0
  [[ -e "$rd_conf" || -L "$rd_conf" || -e "$rd_default" ]] && has_conf=1
  pkg_ready=0
  web_ready=0
  [[ "$(dpkg-query -W -f='${Status} ${Version}' rivendell 2>/dev/null || :)" == "install ok installed 4.5.0-1" ]] && pkg_ready=1
  [[ "$(dpkg-query -W -f='${Status} ${Version}' rivendell-webapi 2>/dev/null || :)" == "install ok installed 4.5.0-1" ]] && web_ready=1

  if (( has_conf == 1 )); then
    [[ -L "$rd_conf" && "$(readlink "$rd_conf")" == "$rd_default" &&
       -f "$rd_default" ]] ||
      fail 'Unrecognized existing Rivendell config; no files changed. Check /etc/rd.conf and /etc/rivendell.d.'
    [[ "$(sudo -n stat -c '%a' "$rd_default")" == 640 ]] ||
      fail 'Existing Rivendell configuration has unexpected permissions; no files changed'
    [[ "$(sudo -n mariadb -NBe "SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='Rivendell'" 2>/dev/null || :)" == 1 ]] ||
      fail 'Configuration exists but the local Rivendell database is missing or inaccessible; no files changed'
    table_count="$(sudo -n mariadb -NBe "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='Rivendell'")" ||
      fail 'Cannot inspect existing Rivendell database tables; no files changed'
    [[ "$table_count" =~ ^[0-9]+$ ]] || fail 'Unexpected schema table count; no files changed'

    if (( pkg_ready == 1 && web_ready == 1 )) && (( table_count > 0 )) &&
       [[ ! -e "$rd_marker" ]]; then
      log 'Rivendell and the database are already installed; preserving both and skipping reinstallation'
      exit 0
    fi
    if [[ -f "$rd_marker" ]] && (( table_count == 0 )) &&
       (( pkg_ready == 0 )); then
      RESUME_STAGED=1
      log 'Verified interrupted first install: matching config, empty database, and first-install marker'
    else
      fail 'Unrecognized partial Rivendell installation; preserving configuration and database for inspection'
    fi
  elif (( pkg_ready == 1 || web_ready == 1 )); then
    fail 'Rivendell package is installed without its expected configuration; no files changed'
  elif [[ "$(sudo -n mariadb -NBe "SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='Rivendell'" 2>/dev/null || echo 0)" != 0 ]]; then
    fail 'Existing Rivendell schema detected without configuration; no files changed'
  fi
fi

# Validate the COMPLETE package transaction BEFORE creating users, databases
# or configuration. A dependency failure must not leave a partial station.
PLAN="$(sudo -n apt-get -s install "$PKG_WEB" "$PKG")" ||
  fail 'APT dependency simulation failed after authentication; inspect the APT error above'
if grep -q '^Remv ' <<<"$PLAN"; then
  printf '%s\n' "$PLAN" >&2
  fail 'Refusing package removal during station initialization'
fi

if (( RESUME_STAGED == 1 )); then
  log 'Preserving staged database and credentials; resuming only the pending Debian package transaction'
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$PKG_WEB" "$PKG"
  for exe in rdadmin rdairplay rdlibrary rdlogmanager rdimport rddbmgr; do
    command -v "$exe" >/dev/null || fail "Installed executable missing: $exe"
  done
  log 'Interrupted Rivendell installation resumed; schema and service created by package postinst'
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
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$PKG_WEB" "$PKG"
for exe in rdadmin rdairplay rdlibrary rdlogmanager rdimport rddbmgr; do
  command -v "$exe" >/dev/null || fail "Installed executable missing: $exe"
done
log 'Installed application/database; NOT BROADCAST-QUALIFIED.'
log 'Log out/in, configure audio and service in RDAdmin, mount NAS read-only.'
log 'Then add [ExternalAudio] Root and References to /etc/rd.conf and index with rdexternal.py.'
 >/dev/null ||
  fail 'Main package is missing RDAirPlay'
[[ "$(dpkg-deb -f "$PKG" Package)" == rivendell ]] || fail 'Wrong main package name'
[[ "$(dpkg-deb -f "$PKG_WEB" Package)" == rivendell-webapi ]] || fail 'Wrong webapi package name'
if [[ "$MODE" == build ]]; then
  log "Built $PKG. No Rivendell database/application installed."
  exit 0
fi

log 'Reauthenticating sudo before package installation; long builds expire sudo timestamps'
sudo -v || fail 'sudo authentication failed; compiled .deb files remain intact'

# Classify previous installation state WITHOUT changing existing files.
# A fresh install has no configuration, database or installed packages.
# A resumable install must have OUR marker, OUR exact config symlink and
# an existing but EMPTY schema, so postinst --create cannot overwrite tables.
# A complete install must have the expected packages and nonempty schema.
# Any other state is deliberately left untouched for manual inspection.
RESUME_STAGED=0
if [[ "$MODE" == install ]]; then
  rd_conf=/etc/rd.conf
  rd_default=/etc/rivendell.d/rd-default.conf
  rd_marker=/etc/rivendell.d/rdcomplete-first-install
  has_conf=0
  [[ -e "$rd_conf" || -L "$rd_conf" || -e "$rd_default" ]] && has_conf=1
  pkg_ready=0
  web_ready=0
  [[ "$(dpkg-query -W -f='${Status} ${Version}' rivendell 2>/dev/null || :)" == "install ok installed 4.5.0-1" ]] && pkg_ready=1
  [[ "$(dpkg-query -W -f='${Status} ${Version}' rivendell-webapi 2>/dev/null || :)" == "install ok installed 4.5.0-1" ]] && web_ready=1

  if (( has_conf == 1 )); then
    [[ -L "$rd_conf" && "$(readlink "$rd_conf")" == "$rd_default" &&
       -f "$rd_default" ]] ||
      fail 'Unrecognized existing Rivendell config; no files changed. Check /etc/rd.conf and /etc/rivendell.d.'
    [[ "$(sudo -n stat -c '%a' "$rd_default")" == 640 ]] ||
      fail 'Existing Rivendell configuration has unexpected permissions; no files changed'
    [[ "$(sudo -n mariadb -NBe "SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='Rivendell'" 2>/dev/null || :)" == 1 ]] ||
      fail 'Configuration exists but the local Rivendell database is missing or inaccessible; no files changed'
    table_count="$(sudo -n mariadb -NBe "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='Rivendell'")" ||
      fail 'Cannot inspect existing Rivendell database tables; no files changed'
    [[ "$table_count" =~ ^[0-9]+$ ]] || fail 'Unexpected schema table count; no files changed'

    if (( pkg_ready == 1 && web_ready == 1 )) && (( table_count > 0 )) &&
       [[ ! -e "$rd_marker" ]]; then
      log 'Rivendell and the database are already installed; preserving both and skipping reinstallation'
      exit 0
    fi
    if [[ -f "$rd_marker" ]] && (( table_count == 0 )) &&
       (( pkg_ready == 0 )); then
      RESUME_STAGED=1
      log 'Verified interrupted first install: matching config, empty database, and first-install marker'
    else
      fail 'Unrecognized partial Rivendell installation; preserving configuration and database for inspection'
    fi
  elif (( pkg_ready == 1 || web_ready == 1 )); then
    fail 'Rivendell package is installed without its expected configuration; no files changed'
  elif [[ "$(sudo -n mariadb -NBe "SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='Rivendell'" 2>/dev/null || echo 0)" != 0 ]]; then
    fail 'Existing Rivendell schema detected without configuration; no files changed'
  fi
fi

# Validate the COMPLETE package transaction BEFORE creating users, databases
# or configuration. A dependency failure must not leave a partial station.
PLAN="$(sudo -n apt-get -s install "$PKG_WEB" "$PKG")" ||
  fail 'APT dependency simulation failed after authentication; inspect the APT error above'
if grep -q '^Remv ' <<<"$PLAN"; then
  printf '%s\n' "$PLAN" >&2
  fail 'Refusing package removal during station initialization'
fi

if (( RESUME_STAGED == 1 )); then
  log 'Preserving staged database and credentials; resuming only the pending Debian package transaction'
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$PKG_WEB" "$PKG"
  for exe in rdadmin rdairplay rdlibrary rdlogmanager rdimport rddbmgr; do
    command -v "$exe" >/dev/null || fail "Installed executable missing: $exe"
  done
  log 'Interrupted Rivendell installation resumed; schema and service created by package postinst'
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
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$PKG_WEB" "$PKG"
for exe in rdadmin rdairplay rdlibrary rdlogmanager rdimport rddbmgr; do
  command -v "$exe" >/dev/null || fail "Installed executable missing: $exe"
done
log 'Installed application/database; NOT BROADCAST-QUALIFIED.'
log 'Log out/in, configure audio and service in RDAdmin, mount NAS read-only.'
log 'Then add [ExternalAudio] Root and References to /etc/rd.conf and index with rdexternal.py.'
