#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup.sh — One-time setup for the voice dictation pipeline
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; }

# ─── 1. Check system dependencies ───────────────────────────────────────────
echo "━━━ Checking system dependencies ━━━"

MISSING=()
for cmd in pw-record ydotool ydotoold notify-send uv; do
    if command -v "$cmd" &>/dev/null; then
        info "$cmd found: $(command -v "$cmd")"
    else
        error "$cmd not found!"
        MISSING+=("$cmd")
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo ""
    error "Missing dependencies: ${MISSING[*]}"
    echo "  Install them with your package manager, e.g.:"
    echo "    sudo pacman -S pipewire ydotool libnotify"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# ─── 2. Install udev rule ───────────────────────────────────────────────────
echo ""
echo "━━━ Installing udev rule for /dev/uinput ━━━"

UDEV_SRC="$SCRIPT_DIR/99-uinput.rules"
UDEV_DST="/etc/udev/rules.d/99-uinput.rules"

if [[ -f "$UDEV_DST" ]]; then
    warn "udev rule already exists at $UDEV_DST — skipping."
else
    sudo cp "$UDEV_SRC" "$UDEV_DST"
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    info "udev rule installed. You may need to re-login for uaccess to apply."
fi

# ─── 3. Install systemd user service ────────────────────────────────────────
echo ""
echo "━━━ Installing ydotoold systemd user service ━━━"

SERVICE_SRC="$SCRIPT_DIR/ydotoold.service"
SERVICE_DST="$HOME/.config/systemd/user/ydotoold.service"

mkdir -p "$(dirname "$SERVICE_DST")"
cp "$SERVICE_SRC" "$SERVICE_DST"
systemctl --user daemon-reload
systemctl --user enable ydotoold.service
systemctl --user start ydotoold.service
info "ydotoold service installed and started."

# ─── 4. Install Python dependencies via uv ───────────────────────────────────
echo ""
echo "━━━ Installing Python dependencies via uv ━━━"

cd "$SCRIPT_DIR"
uv sync
info "Python dependencies installed (uv sync)."

# ─── 5. Make scripts executable ─────────────────────────────────────────────
echo ""
echo "━━━ Finalizing ━━━"

chmod +x "$SCRIPT_DIR/toggle_capture.sh"
chmod +x "$SCRIPT_DIR/process.py"
info "Scripts marked as executable."

# ─── 6. Hyprland config reminder ────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Add this line to ~/.config/hypr/hyprland.conf:"
echo ""
echo "    bind = , F9, exec, $SCRIPT_DIR/toggle_capture.sh"
echo ""
echo "  Then reload Hyprland:  hyprctl reload"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
info "Setup complete! Press F9 to start/stop voice dictation."
