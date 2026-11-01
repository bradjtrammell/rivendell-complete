#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$EUID" -ne 0 ]] || { echo "Run as desktop station user" >&2; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 26.04 ]] || { echo "Ubuntu 26.04 required" >&2; exit 1; }
[[ "$#" -eq 1 && "$1" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_-]{0,9}$ ]] || { echo "Usage: $0 EXISTING_RD_SERVICE" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd -P)"
ROOT="$(cd "$HERE/.." && pwd -P)"
command -v rdlogmanager >/dev/null || { echo "Install Rivendell first" >&2; exit 1; }
install -d -m 0700 "$HOME/.local/bin" "$HOME/.config/systemd/user" "$HOME/.config/rivendell-complete"
[[ ! -e "$HOME/.config/rivendell-complete/loggen.env" ]] || { echo "Configuration already exists; refusing overwrite" >&2; exit 1; }
printf 'RD_SERVICE=%s\n' "$1" > "$HOME/.config/rivendell-complete/loggen.env"
chmod 0600 "$HOME/.config/rivendell-complete/loggen.env"
install -m 0755 "$HERE/rdloggen.py" "$HOME/.local/bin/rdcomplete-loggen"
install -m 0644 "$ROOT/packaging/systemd/rdcomplete-loggen.service" "$HOME/.config/systemd/user/rdcomplete-loggen.service"
install -m 0644 "$ROOT/packaging/systemd/rdcomplete-loggen.timer" "$HOME/.config/systemd/user/rdcomplete-loggen.timer"
systemctl --user daemon-reload
echo "Installed, but intentionally NOT enabled."
echo "Preview: ~/.local/bin/rdcomplete-loggen --service '$1' --dry-run"
echo "Initial generation: systemctl --user start rdcomplete-loggen.service"
echo "Enable repeat: systemctl --user enable --now rdcomplete-loggen.timer"
echo "After-logout operation: sudo loginctl enable-linger $(id -un)"
