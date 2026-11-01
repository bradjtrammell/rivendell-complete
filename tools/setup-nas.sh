#!/usr/bin/env bash
# Mount an existing NAS library read-only without renaming or copying audio.
# Example: sudo ./tools/setup-nas.sh --nfs '192.0.2.10:/music'
# Example: sudo ./tools/setup-nas.sh --smb '//192.0.2.10/music'
set -Eeuo pipefail
umask 077

die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage(){
  cat <<'HELP'
Usage:
  sudo ./tools/setup-nas.sh --nfs HOST:/EXPORT [--mountpoint /mnt/radio-music]
  sudo ./tools/setup-nas.sh --smb //HOST/SHARE [--mountpoint /mnt/radio-music]
Existing NAS audio is read-only. No copying or changing filenames.
SMB asks for credentials interactively; no password in command arguments.
HELP
}
[[ "$EUID" -eq 0 ]] || die 'Run with sudo'
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || die 'Ubuntu 26.04 is required'
proto=; src=; mp=/mnt/radio-music
while (($#)); do
  case "$1" in
    --nfs|--smb)
      [[ -z "$proto" && "$#" -ge 2 ]] || die 'Specify exactly one NAS protocol and share'
      proto="$1";src="$2";shift 2;;
    --mountpoint)
      [[ "$#" -ge 2 ]] || die 'Missing mountpoint'
      mp="$2";shift 2;;
    --help|-h) usage;exit 0;;
    *) die "Unknown option $1";;
  esac
done
[[ -n "$proto" && -n "$src" ]] || { usage; exit 2; }
[[ "$mp" =~ ^/mnt/[A-Za-z0-9_-]+$ ]] || die 'Mountpoint must be a simple direct /mnt/<name> path'
[[ "$src" != *['[:space:],'\'']* ]] || die 'Share path contains invalid whitespace, comma or backslash'
if [[ "$proto" == --nfs ]]; then
  [[ "$src" =~ ^[A-Za-z0-9_.-]+:/[^[:space:],]+$ ]] || die 'NFS must be HOST:/absolute/export'
else
  [[ "$src" =~ ^//[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+$ ]] || die 'SMB must be //HOST/SHARE'
fi
if [[ -e "$mp" ]]; then
  [[ -d "$mp" && ! -L "$mp" ]] || die 'Mountpoint is not a normal directory'
  [[ -z "$(find "$mp" -mindepth 1 -maxdepth 1 -print -quit)" ]] || die 'Mountpoint not empty, refusing to obscure existing files'
  ! mountpoint -q "$mp" || die 'Mountpoint is already mounted'
fi
[[ -z "$(grep -F " $mp " /etc/fstab || true)" ]] || die 'Mountpoint already configured in /etc/fstab'
[[ -z "$(grep -F "$src " /etc/fstab || true)" ]] || die 'Share already configured in /etc/fstab'
if [[ "$proto" == --nfs ]]; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nfs-common
  fstype=nfs
  options='ro,_netdev,nofail,x-systemd.automount,x-systemd.device-timeout=15s,hard,timeo=50,retrans=3'
else
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cifs-utils
  read -r -p 'NAS SMB username: ' username
  [[ -n "$username" && "$username" != *$'\n'* && "$username" != *'='* ]] || die 'Invalid username'
  read -r -s -p 'NAS SMB password: ' password; printf '\n'
  [[ -n "$password" && "$password" != *$'\n'* ]] || die 'Invalid password'
  install -d -m 0700 /etc/rivendell-complete
  [[ ! -e /etc/rivendell-complete/nas.cred ]] || die 'NAS credential file already exists'
  cred_tmp="$(mktemp /etc/rivendell-complete/.cred.XXXXXX)"
  trap 'rm -f "$cred_tmp"' EXIT
  # The credentials file is root-only. Passwords are never written into fstab.
  printf 'username=%s\npassword=%s\n' "$username" "$password" > "$cred_tmp"
  chmod 0600 "$cred_tmp"
  mv -n "$cred_tmp" /etc/rivendell-complete/nas.cred
  unset password
  fstype=cifs
  options='ro,credentials=/etc/rivendell-complete/nas.cred,vers=3.1.1,iocharset=utf8,_netdev,nofail,x-systemd.automount,x-systemd.device-timeout=15s'
fi
mkdir -p "$mp"
backup="/etc/fstab.rivendell-complete.$(date +%Y%m%d%H%M%S)"
cp -p /etc/fstab "$backup"
printf '\n# Rivendell Complete: original NAS music, READ-ONLY\n%s %s %s %s 0 0\n' \
  "$src" "$mp" "$fstype" "$options" >> /etc/fstab
systemctl daemon-reload
if ! mount "$mp"; then
  # Safe failure: no mutation of original NAS; preserve backup for inspection.
  echo "NAS mounting failed. Reverting our /etc/fstab entry." >&2
  cp "$backup" /etc/fstab
  systemctl daemon-reload
  exit 1
fi
mount_opts="$(findmnt -rn -o OPTIONS --target "$mp" || true)"
[[ ",$mount_opts," == *,ro,* ]] || die 'NAS did not mount read-only; unmount and inspect immediately'
printf 'NAS source: %s\nMounted read-only at: %s\n' "$src" "$mp"
echo 'Original music untouched. Configure [ExternalAudio] Root to this mountpoint.'
