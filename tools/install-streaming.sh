#!/usr/bin/env bash
# Run as the DESKTOP STUDIO USER. Does not enable or start streaming.
set -Eeuo pipefail
umask 077
[[ $EUID -ne 0 ]] || { echo "Run as normal desktop user, not root" >&2; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || { echo "Ubuntu 26.04 required" >&2; exit 1; }
here="$(cd "$(dirname "$0")" && pwd -P)"
[[ -f "$here/rdstream.py" && -f "$here/rdmetadata.py" && -f "$here/../packaging/systemd/rdcomplete-stream.service" ]] || {
  echo "Run from the checked-out Rivendell Complete source tree" >&2
  exit 1
}
# The core Ubuntu installer already refreshed APT metadata. Running a second
# update here adds a separate lists lock and creates an avoidable race with
# another desktop update. Let APT itself wait for the dpkg frontend lock.
# Never remove lock files or terminate an unrelated package manager.
sudo -v
echo 'Installing GlassCoder/JACK; waiting up to 300 seconds for any active dpkg transaction'
if ! sudo env DEBIAN_FRONTEND=noninteractive apt-get \
    -o DPkg::Lock::Timeout=300 \
    install -y --no-install-recommends glasscoder jack-tools jackd2; then
  echo 'ERROR: GlassCoder/JACK package installation failed or package lock timed out.' >&2
  echo 'Check any other apt process with: ps -eo pid,ppid,etime,stat,cmd | grep -E "[a]pt-get|[d]pkg|[u]nattended-upgrade"' >&2
  echo 'The Rivendell database, compiled packages, and station configuration have not been removed.' >&2
  exit 1
fi
install -d -m 0700 "$HOME/.local/bin" "$HOME/.config/systemd/user"
install -m 0755 "$here/rdstream.py" "$HOME/.local/bin/rdcomplete-stream"
install -m 0755 "$here/rdmetadata.py" "$HOME/.local/bin/rdcomplete-metadata"
install -m 0755 "$here/pypad_glasscoder.py" "$HOME/.local/bin/pypad_glasscoder.py"
install -m 0755 "$here/rdsweepers.py" "$HOME/.local/bin/rdsweepers.py"
install -m 0755 "$here/rdjackroute.py" "$HOME/.local/bin/rdcomplete-jack-route"
install -m 0644 "$here/../packaging/systemd/rdcomplete-stream.service" \
  "$HOME/.config/systemd/user/rdcomplete-stream.service"
install -m 0644 "$here/../packaging/systemd/rdcomplete-jack-route.service" "$HOME/.config/systemd/user/rdcomplete-jack-route.service"
if systemctl --user daemon-reload; then
  echo 'User service definitions reloaded.'
else
  echo 'WARNING: User systemd manager unavailable in this SSH session.' >&2
  echo 'User unit files are staged; log into the Ubuntu desktop and run: systemctl --user daemon-reload' >&2
fi
echo "Encoder installed, NOT started."
echo "Configure: ~/.local/bin/rdcomplete-stream configure --server-type Shout2 --server-url http://HOST:PORT/ --username source"
echo "Validate: ~/.local/bin/rdcomplete-stream verify"
echo "Then: systemctl --user enable --now rdcomplete-stream.service"
echo "Route JACK outputs into the glasscoder input ports; verify on a PRIVATE test stream."
echo "Create a PyPAD GlassCoder instance in RDAdmin; script: ~/.local/bin/pypad_glasscoder.py"
echo "Set its MetadataFifo path to ~/.local/state/rivendell-complete/encoder-metadata.fifo"

echo "Discover actual JACK audio ports: ~/.local/bin/rdcomplete-jack-route --discover"
echo "Configure stereo: rdcomplete-jack-route --set SRC_LEFT DEST_LEFT SRC_RIGHT DEST_RIGHT"
echo "Enable reconnection: systemctl --user enable --now rdcomplete-jack-route.service"
