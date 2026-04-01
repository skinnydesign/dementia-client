# Dementia Client

A Python/Flask dashboard designed to run on a Raspberry Pi as an always-on display. It connects to the **dementia** Laravel API and caches all data locally in SQLite so the display keeps working even without an internet connection.

## Features

- **Todos** — shows pending todos synced from the Laravel app
- **Schedule** — recurring reminders (daily / every other day / weekly) with a full-screen alarm popup and sound when due
- **Calendar** — upcoming events from a Google Calendar iCal feed
- **Alerts** — instant messages pushed from the Laravel app to the display
- **Dashboard** — configurable widget layout (clock, todos, schedule, calendar)
- **WiFi setup** — scan and connect to networks from the login screen (no login required)
- **Offline support** — all data served from local SQLite cache, synced every 5 minutes when online
- **Offline writes** — marking todos/schedule complete works offline and syncs when reconnected

## Requirements

- Python 3.11+
- Docker & Docker Compose (recommended for development), **or** a plain Python environment (recommended for Raspberry Pi)
- A running instance of the **dementia** Laravel API

---

## Quick Start (Docker — development)

```bash
# 1. Clone the repo
git clone https://github.com/skinnydesign/dementia-client.git
cd dementia-client

# 2. Create environment file
cp .env.example .env
# Edit .env — set API_BASE_URL and SECRET_KEY

# 3. Create the external proxy network if it doesn't exist
docker network create proxy

# 4. Start
docker compose up -d

# Open http://localhost:8000
```

---

## Quick Start (Raspberry Pi — recommended)

Docker is not recommended on the Pi Zero due to limited RAM (512MB). Use the setup script instead — it configures everything in one go.

### 1. Flash Raspberry Pi OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash **Raspberry Pi OS with Desktop** to your SD card. In the imager's advanced options you can pre-configure your WiFi credentials and enable SSH so you don't need a keyboard/monitor for setup.

### 2. Boot and run the setup script

SSH in (or open a terminal on the Pi) and run:

```bash
curl -sSL https://raw.githubusercontent.com/skinnydesign/dementia-client/main/setup.sh | sudo bash
```

Or if you've already cloned the repo:

```bash
sudo bash setup.sh
```

The script will ask for your `API_BASE_URL` and `SECRET_KEY`, then handle everything:

- Installs all system dependencies
- Clones the repo and sets up a Python virtual environment
- Writes the `.env` file
- Configures passwordless sudo for WiFi commands
- Creates and enables the systemd service
- Enables desktop auto-login
- Configures Chromium in kiosk mode to launch on boot
- Disables screen blanking

When it finishes, reboot:

```bash
sudo reboot
```

The Pi will boot straight into the kiosk display.

### Cloning for multiple devices

Once you have one Pi set up and working, you can clone the SD card to provision additional devices without running the setup script again:

```bash
# On your Mac/Linux machine — find your SD card device first with `diskutil list` (Mac) or `lsblk` (Linux)
sudo dd if=/dev/sdX of=dementia-client.img bs=4M status=progress
```

Then flash `dementia-client.img` to each new SD card using Raspberry Pi Imager ("Use custom image").

---

## Environment Variables

Create a `.env` file in the project root:

```env
API_BASE_URL=http://your-laravel-app.com/api
SECRET_KEY=change-me-to-something-random
DATA_DIR=/data
```

| Variable | Description |
|---|---|
| `API_BASE_URL` | Full URL to the Laravel API (include `/api`) |
| `SECRET_KEY` | Flask session secret — set to something random |
| `DATA_DIR` | Where the SQLite database is stored (default: `~`) |

---

## Project Structure

```
dementia-client/
├── app/
│   ├── app.py          # Flask app — all routes
│   ├── db.py           # SQLite cache — all reads/writes
│   └── sync.py         # Background sync from Laravel (every 5 min)
├── static/
│   ├── css/style.css   # Animations and scrollbar only (layout is Tailwind)
│   └── js/app.js       # Flash message auto-dismiss
├── templates/
│   ├── base.html       # Shared layout, schedule alarm, alert banner
│   ├── login.html      # Sign in page (includes WiFi setup link)
│   ├── wifi_setup.html # WiFi setup (no login required)
│   ├── dashboard.html  # Configurable widget layout page
│   ├── todos.html      # Todos + schedule + calendar page
│   ├── index.html      # Settings page
│   └── widgets/
│       ├── clock.html
│       ├── todos.html
│       ├── schedule.html
│       └── ical.html
├── data/               # SQLite database (git-ignored)
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## How Syncing Works

1. On login, an immediate sync runs to populate the local database
2. A background thread syncs from Laravel every **5 minutes**
3. The iCal feed is re-fetched every **30 minutes**
4. All page data (todos, schedule, alert, calendar, layout) is served from SQLite — no API call on page load
5. Completions (todos, schedule) are written to SQLite immediately and pushed to Laravel. If offline, they are queued and pushed next time the network is available

---

## WiFi Setup (Raspberry Pi)

WiFi scan and connect uses `wpa_cli` and `iwgetid`, which are included with `wpasupplicant` and `wireless-tools` on Raspberry Pi OS.

The WiFi setup page is available at `/wifi-setup` **without logging in**, so users can connect the device to their network before signing in.

> **Note:** Raspberry Pi OS Bookworm (2023+) switched to NetworkManager by default. If you are running Bookworm, `wpa_cli` may not be active. You can either switch back to wpa_supplicant or install NetworkManager and adapt the WiFi functions in `app/app.py` to use `nmcli`.

---

## Hardware Recommendation

| Model | RAM | Recommended? |
|---|---|---|
| Pi Zero (original) | 512MB | Works but slow — browser + server is tight |
| **Pi Zero 2 W** | 512MB | **Recommended** — quad-core, much faster |
| Pi 3 / 4 | 1GB+ | Ideal if available |

---

## Laravel API

This client connects to the **dementia** Laravel app. The following API endpoints are used:

| Endpoint | Purpose |
|---|---|
| `POST /api/token` | Login |
| `DELETE /api/token` | Logout |
| `GET /api/apiTodos` | Fetch todos |
| `PUT /api/apiTodos/{id}/complete` | Complete a todo |
| `GET /api/schedule` | Fetch schedule items with completion history |
| `PUT /api/schedule/{id}/complete` | Complete a schedule item |
| `GET /api/ical` | Fetch iCal settings (URL + days ahead) |
| `GET /api/alert` | Fetch current active alert |
| `GET /api/layout` | Fetch dashboard widget layout |
