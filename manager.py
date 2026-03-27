"""
WiFi Manager
============
Uses nmcli (NetworkManager CLI) which is available on:
  - Raspberry Pi OS (Bookworm/Bullseye)
  - Ubuntu / Debian with NetworkManager installed
  - Most modern Linux desktops

Falls back gracefully if nmcli is not available (e.g. dev on macOS/Windows).
"""
import subprocess
import shutil
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WifiNetwork:
    ssid:     str
    signal:   int          # 0-100
    security: str          # WPA2, WPA3, Open, etc.
    in_use:   bool = False
    bssid:    str  = ''

    @property
    def signal_bars(self) -> int:
        """Convert signal % to 1-4 bars."""
        if self.signal >= 75: return 4
        if self.signal >= 50: return 3
        if self.signal >= 25: return 2
        return 1


def _nmcli_available() -> bool:
    return shutil.which('nmcli') is not None


def scan_networks() -> tuple[list[WifiNetwork], Optional[str]]:
    """
    Scan for WiFi networks.
    Returns (networks, error_message).
    """
    if not _nmcli_available():
        return _mock_networks(), None

    try:
        # Trigger a rescan first (may require sudo depending on setup)
        subprocess.run(['nmcli', 'dev', 'wifi', 'rescan'],
                       capture_output=True, timeout=10)

        result = subprocess.run(
            ['nmcli', '-t', '-f', 'IN-USE,SSID,BSSID,SIGNAL,SECURITY',
             'dev', 'wifi', 'list'],
            capture_output=True, text=True, timeout=15
        )

        if result.returncode != 0:
            return [], result.stderr.strip() or 'nmcli scan failed'

        networks = []
        seen_ssids = set()

        for line in result.stdout.strip().splitlines():
            parts = line.split(':')
            if len(parts) < 5:
                continue

            in_use   = parts[0].strip() == '*'
            ssid     = parts[1].strip()
            bssid    = parts[2].strip()
            signal   = int(parts[3].strip()) if parts[3].strip().isdigit() else 0
            security = parts[4].strip() or 'Open'

            if not ssid or ssid in seen_ssids:
                continue

            seen_ssids.add(ssid)
            networks.append(WifiNetwork(
                ssid=ssid, signal=signal, security=security,
                in_use=in_use, bssid=bssid,
            ))

        networks.sort(key=lambda n: (-n.signal, n.ssid))
        return networks, None

    except subprocess.TimeoutExpired:
        return [], 'Scan timed out'
    except Exception as e:
        return [], str(e)


def connect_network(ssid: str, password: str = None) -> tuple[bool, str]:
    """
    Connect to a WiFi network.
    Returns (success, message).
    """
    if not _nmcli_available():
        return True, f'[Mock] Connected to {ssid}'

    try:
        if password:
            cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid,
                   'password', password]
        else:
            cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            return True, f'Connected to {ssid}'
        else:
            msg = result.stderr.strip() or result.stdout.strip() or 'Connection failed'
            return False, msg

    except subprocess.TimeoutExpired:
        return False, 'Connection timed out'
    except Exception as e:
        return False, str(e)


def disconnect_network() -> tuple[bool, str]:
    """Disconnect from the current WiFi network."""
    if not _nmcli_available():
        return True, '[Mock] Disconnected'

    try:
        result = subprocess.run(
            ['nmcli', 'dev', 'disconnect', 'wlan0'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True, 'Disconnected'
        return False, result.stderr.strip() or 'Disconnect failed'
    except Exception as e:
        return False, str(e)


def get_current_connection() -> Optional[str]:
    """Return the SSID of the currently connected network, or None."""
    if not _nmcli_available():
        return 'MockNet-5G'

    try:
        result = subprocess.run(
            ['nmcli', '-t', '-f', 'ACTIVE,SSID', 'dev', 'wifi'],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            parts = line.split(':')
            if len(parts) >= 2 and parts[0] == 'yes':
                return parts[1].strip()
    except Exception:
        pass
    return None


def _mock_networks() -> list[WifiNetwork]:
    """Return fake data for development on non-Linux systems."""
    return [
        WifiNetwork('MockNet-5G',       92, 'WPA2',  in_use=True),
        WifiNetwork('Neighbor_WiFi',    78, 'WPA2'),
        WifiNetwork('CoffeeShop_Free',  55, 'Open'),
        WifiNetwork('TP-Link_2.4G',     41, 'WPA2'),
        WifiNetwork('AndroidAP_7f3a',   22, 'WPA3'),
    ]
