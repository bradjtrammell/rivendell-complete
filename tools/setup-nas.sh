#!/usr/bin/env bash
# Rivendell Complete: mount original NFS/SMB media read-only.
# This script never imports, copies, renames, writes to, or deletes NAS audio.
set -Eeuo pipefail
umask 077

die() { printf 'Rivendell Complete NAS: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'HELP'
Usage:
  sudo bash tools/setup-nas.sh --nfs HOST:/absolute/export [--mountpoint /mnt/radio-music]
  sudo bash tools/setup-nas.sh --smb //HOST/SHARE [--mountpoint /mnt/radio-music]

Requirements: fresh Ubuntu 26.04, unused mountpoint, no conflicting /etc/fstab entry.
The media share is mounted read-only. SMB credentials are prompted privately,
stored mode 0600 under /etc/rivendell-complete, and never put on the command line.
HELP
}
if [[ "$#" -eq 1 && ( "$1" == -h || "$1" == --help ) ]]; then usage; exit 0; fi
[[ "$EUID" -eq 0 ]] || die 'Run with sudo (requires root to configure mounts)'
[[ -r /etc/os-release ]] || die 'Missing /etc/os-release'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || die 'Ubuntu 26.04 required'

proto= src= mp=/mnt/radio-music
while (($#)); do
  case "$1" in
    --nfs|--smb)
      [[ -z "$proto" && "$#" -ge 2 ]] || die 'Specify exactly one NAS protocol and share'
      proto="$1"; src="$2"; shift 2 ;;
    --mountpoint)
      [[ "$#" -ge 2 ]] || die 'Missing mountpoint value'
      mp="$2"; shift 2 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ -n "$proto" && -n "$src" ]] || { usage >&2; exit 2; }
[[ "$mp" =~ ^/mnt/[A-Za-z0-9_-]+$ ||
   "$mp" =~ ^/mnt/radio-music/[a-z][a-z0-9_-]{0,31}$ ]] ||
  die 'Mountpoint must be /mnt/name or /mnt/radio-music/SOURCE_NAME'
if [[ "$mp" == /mnt/radio-music/* ]]; then
  [[ "${mp##*/}" != legacy ]] ||
    die 'The source name legacy is reserved for existing direct-root mounts'
  [[ ! -L /mnt/radio-music ]] || die 'NAS collection root cannot be a symlink'
  [[ ! -e /mnt/radio-music || -d /mnt/radio-music ]] ||
    die 'NAS collection root is not a directory'
  mountpoint -q /mnt/radio-music &&
    die 'Legacy NAS mount occupies the collection root; refusing to hide existing music'
fi
nas_credentials=/etc/rivendell-complete/nas.cred
if [[ "$mp" == /mnt/radio-music/* ]]; then
  nas_credentials="/etc/rivendell-complete/nas-${mp##*/}.cred"
fi
# /etc/fstab fields are unescaped: refuse whitespace, comments, commas, and backslashes.
[[ "$src" != *[[:space:]]* && "$src" != *'#'* && "$src" != *','* && "$src" != *'\'* ]] ||
  die 'Share contains a character unsafe for /etc/fstab'
if [[ "$proto" == --nfs ]]; then
  [[ "$src" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*:/[A-Za-z0-9_./-]+$ ]] ||
    die 'NFS source must be HOST:/absolute/export'
  fstype=nfs
else
  [[ "$src" =~ ^//[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_./-]+$ ]] ||
    die 'SMB source must be //HOST/SHARE'
  fstype=cifs
fi

# Prevent two invocations from changing fstab concurrently.
exec 9>/run/lock/rivendell-complete-nas.lock
flock -n 9 || die 'Another NAS configuration is running'
if [[ -e "$mp" ]]; then
  [[ -d "$mp" && ! -L "$mp" ]] || die 'Mountpoint is not a normal directory'
  mountpoint -q "$mp" && die 'Mountpoint is already mounted'
  [[ -z "$(find "$mp" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
    die 'Mountpoint is not empty; refusing to hide files'
fi
[[ -f /etc/fstab && ! -L /etc/fstab ]] || die 'Invalid /etc/fstab'
if awk -v source="$src" -v target="$mp" '
  $1 !~ /^#/ && ($1 == source || $2 == target) { collision=1 }
  END { exit !collision }
' /etc/fstab; then
  die 'Share or mountpoint already configured in /etc/fstab'
fi

if [[ "$proto" == --nfs ]]; then
  if [[ "$(dpkg-query -W -f='\${Status}' nfs-common 2>/dev/null || :)" != 'install ok installed' ]]; then
    DEBIAN_FRONTEND=noninteractive apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nfs-common
  fi
  options='ro,_netdev,nofail,x-systemd.automount,x-systemd.device-timeout=15s,hard,timeo=50,retrans=3'
else
  if [[ "$(dpkg-query -W -f='\${Status}' cifs-utils 2>/dev/null || :)" != 'install ok installed' ]]; then
    DEBIAN_FRONTEND=noninteractive apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cifs-utils
  fi
  read -r -p 'NAS SMB username: ' username
  [[ -n "$username" && "$username" != *[[:cntrl:]]* && "$username" != *'='* && "$username" != *'\'* ]] ||
    die 'Invalid SMB username'
  read -r -s -p 'NAS SMB password: ' password; printf '\n'
  [[ -n "$password" && "$password" != *$'\n'* && "$password" != *$'\r'* ]] ||
    die 'Invalid SMB password'
  options="ro,credentials=$nas_credentials,vers=3.1.1,iocharset=utf8,_netdev,nofail,x-systemd.automount,x-systemd.device-timeout=15s"
fi

# Do not overwrite an existing credential file.
if [[ "$proto" == --smb ]]; then
  install -d -o root -g root -m 0700 /etc/rivendell-complete
  [[ ! -e "$nas_credentials" && ! -L "$nas_credentials" ]] ||
    die 'SMB credential file already exists; refusing overwrite'
fi
backup=
temp=
credential_created=0
fstab_changed=0
written_sha=
on_error() {
  local rc=$?
  trap - ERR
  if [[ "$fstab_changed" -eq 1 && -n "$backup" && -n "$written_sha" &&
        "$(sha256sum /etc/fstab | cut -d' ' -f1)" == "$written_sha" ]]; then
    umount "$mp" >/dev/null 2>&1 || true
    cp -p "$backup" /etc/fstab || true
    systemctl daemon-reload || true
  fi
  if [[ "$credential_created" -eq 1 ]]; then
    rm -f "$nas_credentials"
  fi
  printf 'Rivendell Complete NAS: mount/configuration failed (status %s); check connectivity and source permissions\n' "$rc" >&2
  exit "$rc"
}
trap on_error ERR
trap 'if [[ -n "$temp" ]]; then rm -f "$temp"; fi' EXIT
if [[ "$proto" == --smb ]]; then
  credential_temp="$(mktemp /etc/rivendell-complete/.nas.XXXXXX)"
  chmod 0600 "$credential_temp"
  printf 'username=%s\npassword=%s\n' "$username" "$password" > "$credential_temp"
  unset password
  mv -n "$credential_temp" "$nas_credentials"
  [[ -f "$nas_credentials" ]] || die 'Could not install credential file'
  credential_created=1
fi

# Atomic fstab replacement and a timestamped, root-only recovery copy.
backup="/etc/fstab.rivendell-complete.$(date -u +%Y%m%dT%H%M%SZ).$$"
cp -p /etc/fstab "$backup"
chmod 0600 "$backup"
temp="$(mktemp /etc/.fstab.rivendell-complete.XXXXXX)"
cp -p /etc/fstab "$temp"
printf '\n# Rivendell Complete original audio: READ ONLY\n%s %s %s %s 0 0\n' \
  "$src" "$mp" "$fstype" "$options" >> "$temp"
chmod 0644 "$temp"
if [[ "$mp" == /mnt/radio-music/* ]]; then
  if [[ ! -d /mnt/radio-music ]]; then
    install -d -m 0755 /mnt/radio-music
  fi
fi
mkdir -p "$mp"
mv -f "$temp" /etc/fstab
temp=
fstab_changed=1
written_sha="$(sha256sum /etc/fstab | cut -d' ' -f1)"
systemctl daemon-reload
mount "$mp"
# This also triggers systemd automount on systems using that mechanism.
stat "$mp/." >/dev/null
actual_type="$(findmnt -rn -T "$mp" -o FSTYPE)"
actual_options="$(findmnt -rn -T "$mp" -o OPTIONS)"
if [[ "$proto" == --nfs ]]; then
  if [[ "$actual_type" != nfs && "$actual_type" != nfs4 ]]; then
    printf "Expected NFS mount; found %s\n" "$actual_type" >&2
    false
  fi
else
  if [[ "$actual_type" != cifs ]]; then
    printf "Expected CIFS mount; found %s\n" "$actual_type" >&2
    false
  fi
fi
if [[ ",$actual_options," != *,ro,* ]]; then
  printf "Mount is NOT read-only; refusing success\n" >&2
  false
fi

credential_created=0
fstab_changed=0
trap - ERR
printf 'NAS mounted and verified read-only: %s -> %s (%s)\n' "$src" "$mp" "$actual_type"
printf 'Recovery copy of original fstab: %s\n' "$backup"
if [[ "$mp" == /mnt/radio-music/* ]]; then
  printf 'Set [ExternalAudio] Root=/mnt/radio-music (named multi-source library).\n'
else
  printf 'Set [ExternalAudio] Root=%s in the local Rivendell configuration.\n' "$mp"
fi
