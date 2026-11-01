#!/usr/bin/env bash
# Run as the DESKTOP STUDIO USER. Does not enable or start streaming.
set -Eeuo pipefail
[[ $EUID -ne 0 ]] || { echo "Run as normal desktop user, not root" >&2; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || { echo "Ubuntu 26.04 required" >&2; exit 1; }
here="$(cd "$(dirname "$0")" && pwd -P)"
[[ -f "$here/rdstream.py" && -f "$here/rdmetadata.py" && -f "$here/../packaging/systemd/rdcomplete-stream.service" ]] || {
  echo "Run from the checked-out Rivendell Complete source tree" >&2
  exit 1
}
sudo apt-get update
sudo apt-get install -y --no-install-recommends glasscoder
install -d -m 0700 "$HOME/.local/bin" "$HOME/.config/systemd/user"
install -m 0755 "$here/rdstream.py" "$HOME/.local/bin/rdcomplete-stream"
install -m 0755 "$here/rdmetadata.py" "$HOME/.local/bin/rdcomplete-metadata"
install -m 0644 "$here/../packaging/systemd/rdcomplete-stream.service" \
  "$HOME/.config/systemd/user/rdcomplete-stream.service"
systemctl --user daemon-reload
echo "Encoder installed, NOT started."
echo "Configure: ~/.local/bin/rdcomplete-stream configure --server-type Shout2 --server-url http://HOST:PORT/ --username source"
echo "Validate: ~/.local/bin/rdcomplete-stream verify"
echo "Then: systemctl --user enable --now rdcomplete-stream.service"
echo "Route JACK outputs into the glasscoder input ports; verify on a PRIVATE test stream."
