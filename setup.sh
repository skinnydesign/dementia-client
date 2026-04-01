#!/bin/bash
# ─── Dementia Client — Raspberry Pi Setup ────────────────────────────────────
# Run on a fresh Raspberry Pi OS (with Desktop) installation.
# Usage: sudo bash setup.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
AMBER='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="/home/pi/dementia-client"
SERVICE_NAME="dementia-client"
REPO_URL="https://github.com/skinnydesign/dementia-client.git"

print_header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "   Dementia Client — Raspberry Pi Setup"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

step() {
    echo -e "${BLUE}▸${NC} $1"
}

ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

# ─── Root check ───────────────────────────────────────────────────────────────

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo bash setup.sh${NC}"
    exit 1
fi

print_header

# ─── Gather config ────────────────────────────────────────────────────────────

echo -e "${AMBER}Configuration${NC}"
echo ""

read -r -p "  API_BASE_URL (e.g. https://yourapp.com/api): " API_BASE_URL </dev/tty || true
while [ -z "$API_BASE_URL" ]; do
    echo -e "  ${RED}API_BASE_URL is required.${NC}"
    read -r -p "  API_BASE_URL: " API_BASE_URL </dev/tty || true
done

read -r -p "  SECRET_KEY (leave blank to auto-generate): " SECRET_KEY </dev/tty || true
if [ -z "$SECRET_KEY" ]; then
    SECRET_KEY=$(openssl rand -hex 32)
    ok "Generated SECRET_KEY: $SECRET_KEY"
fi

echo ""
echo -e "${GREEN}Starting installation...${NC}"
echo ""

# ─── System packages ──────────────────────────────────────────────────────────

step "Updating system packages (this may take a few minutes)..."
apt-get update -qq
apt-get upgrade -y -qq
ok "System up to date"

step "Installing dependencies..."
apt-get install -y -qq \
    python3-pip \
    python3-venv \
    wpasupplicant \
    wireless-tools \
    git \
    unclutter

# Chromium package name changed in Bookworm
if apt-cache show chromium &>/dev/null; then
    apt-get install -y -qq chromium
    CHROMIUM_BIN="chromium"
else
    apt-get install -y -qq chromium-browser
    CHROMIUM_BIN="chromium-browser"
fi
ok "Dependencies installed (chromium: $CHROMIUM_BIN)"

# ─── App install ──────────────────────────────────────────────────────────────

step "Installing application..."
if [ -d "$INSTALL_DIR/.git" ]; then
    sudo -u pi git -C "$INSTALL_DIR" pull --ff-only
    ok "Repository updated"
else
    sudo -u pi git clone "$REPO_URL" "$INSTALL_DIR"
    ok "Repository cloned"
fi

step "Setting up Python environment..."
sudo -u pi python3 -m venv "$INSTALL_DIR/venv"
sudo -u pi "$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u pi "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
ok "Python environment ready"

# ─── Data directory ───────────────────────────────────────────────────────────

mkdir -p /data
chown pi:pi /data
ok "Data directory created at /data"

# ─── .env file ────────────────────────────────────────────────────────────────

step "Writing .env..."
cat > "$INSTALL_DIR/.env" << EOF
API_BASE_URL=${API_BASE_URL}
SECRET_KEY=${SECRET_KEY}
DATA_DIR=/data
EOF
chown pi:pi "$INSTALL_DIR/.env"
ok ".env written"

# ─── Sudoers for WiFi ─────────────────────────────────────────────────────────

step "Configuring passwordless sudo for WiFi commands..."
cat > /etc/sudoers.d/dementia-wifi << 'EOF'
pi ALL=(ALL) NOPASSWD: /sbin/wpa_cli, /sbin/iwgetid
EOF
chmod 0440 /etc/sudoers.d/dementia-wifi
ok "Sudoers configured"

# ─── Systemd service ──────────────────────────────────────────────────────────

step "Creating systemd service..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=Dementia Client
After=network.target

[Service]
User=pi
WorkingDirectory=${INSTALL_DIR}/app
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn -w 2 -b 0.0.0.0:8000 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl start ${SERVICE_NAME}
ok "Service enabled and started"

# ─── Auto-login to desktop ────────────────────────────────────────────────────

step "Enabling desktop auto-login..."
raspi-config nonint do_boot_behaviour B4
ok "Auto-login enabled"

# ─── Kiosk autostart ─────────────────────────────────────────────────────────

step "Configuring kiosk autostart..."
AUTOSTART_DIR="/etc/xdg/lxsession/LXDE-pi"
mkdir -p "$AUTOSTART_DIR"
cat > "${AUTOSTART_DIR}/autostart" << EOF
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xset s off
@xset s noblank
@xset -dpms
@unclutter -idle 0.5 -root
@${CHROMIUM_BIN} --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble --disable-restore-session-state http://localhost:8000
EOF
ok "Kiosk autostart configured"

# ─── Disable screen blanking system-wide ────────────────────────────────────

step "Disabling screen blanking..."
if ! grep -q "consoleblank=0" /boot/cmdline.txt 2>/dev/null; then
    sed -i 's/$/ consoleblank=0/' /boot/cmdline.txt
fi
ok "Screen blanking disabled"

# ─── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  ${GREEN}Setup complete!${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Check service:  systemctl status ${SERVICE_NAME}"
echo "  View logs:      journalctl -u ${SERVICE_NAME} -f"
echo ""
echo -e "  ${AMBER}Reboot to launch the kiosk:${NC}"
echo ""
echo "    sudo reboot"
echo ""
