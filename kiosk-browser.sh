#!/bin/bash
# ─── Dementia Client — switch kiosk browser ──────────────────────────────────
# Chooses which browser the Pi launches at login (labwc / Wayland desktops).
# Usage: sudo ./kiosk-browser.sh cog|chromium|status
#   cog      — WPE WebKit, much lighter on memory (installed on first use)
#   chromium — the original Chromium --kiosk setup
#   status   — show which browser is configured
# Reboot (or log out and back in) to apply.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

URL="http://localhost:8000"

step() {
    echo -e "${BLUE}▸${NC} $1"
}

ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
    echo -e "${RED}$1${NC}"
    exit 1
}

CHOICE="$1"
case "$CHOICE" in
    cog|chromium|status) ;;
    *) fail "Usage: sudo $0 cog|chromium|status" ;;
esac

# ─── Detect the real user (whoever ran sudo) ──────────────────────────────────

REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo '')}"
if [ -z "$REAL_USER" ] || [ "$REAL_USER" = "root" ]; then
    fail "Could not detect the non-root user. Please run as: sudo $0 $CHOICE"
fi
REAL_HOME=$(eval echo "~$REAL_USER")
LABWC_DIR="${REAL_HOME}/.config/labwc"
STATE_FILE="${REAL_HOME}/.config/dementia-kiosk-browser"

if [ "$CHOICE" = "status" ]; then
    echo "Configured kiosk browser: $(cat "$STATE_FILE" 2>/dev/null || echo 'unknown (chromium if set up by setup.sh)')"
    exit 0
fi

[ "$EUID" -eq 0 ] || fail "Please run as root: sudo $0 $CHOICE"

if ! command -v labwc &>/dev/null; then
    fail "labwc not found — browser switching only supports Raspberry Pi OS Bookworm or later (Wayland)."
fi

# ─── Build the launch command ────────────────────────────────────────────────

if [ "$CHOICE" = "cog" ]; then
    step "Installing Cog (WPE WebKit) + GStreamer audio..."
    # GStreamer plugins are needed for Web Audio (the schedule alarm chime)
    apt-get install -y -qq cog gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-alsa
    ok "Cog installed"
    LAUNCH="COG_PLATFORM_WL_VIEW_FULLSCREEN=1 cog --platform=wl ${URL} &"
else
    if command -v chromium &>/dev/null; then
        CHROMIUM_BIN="chromium"
    elif command -v chromium-browser &>/dev/null; then
        CHROMIUM_BIN="chromium-browser"
    else
        step "Installing Chromium..."
        if apt-cache show chromium &>/dev/null; then
            apt-get install -y -qq chromium
            CHROMIUM_BIN="chromium"
        else
            apt-get install -y -qq chromium-browser
            CHROMIUM_BIN="chromium-browser"
        fi
    fi
    LAUNCH="${CHROMIUM_BIN} --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble --disable-restore-session-state --password-store=basic ${URL} &"
fi

# ─── Write labwc autostart ───────────────────────────────────────────────────

step "Configuring kiosk autostart (${CHOICE})..."
mkdir -p "$LABWC_DIR"
printf '#!/bin/bash\nsleep 5\n%s\n' "$LAUNCH" > "${LABWC_DIR}/autostart"
chmod +x "${LABWC_DIR}/autostart"
echo "$CHOICE" > "$STATE_FILE"
chown -R "${REAL_USER}:${REAL_USER}" "$LABWC_DIR" "$STATE_FILE"
ok "Kiosk will launch ${CHOICE} at next login — reboot to apply"
