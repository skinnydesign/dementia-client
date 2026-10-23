# Dementia Client

A Python/Flask dashboard designed to run on a Raspberry Pi as an always-on display. It connects to the **dementia** Laravel API and caches all data locally in SQLite so the display keeps working even without an internet connection.

## Features

- **Todos** — shows pending todos synced from the Laravel app; tap anywhere on a row to mark complete
- **Schedule** — recurring reminders (daily / every other day / weekly) with a full-screen alarm popup and sound when due
- **Calendar** — upcoming events from a Google Calendar iCal feed
- **Alerts** — instant messages pushed from the Laravel app to the display
- **Dashboard** — configurable widget layout (clock, todos, schedule, calendar)
- **WiFi setup** — scan and connect to networks from the login screen (no login required)
- **Offline support** — all data served from local SQLite cache, synced every 5 minutes when online
- **Offline writes** — marking todos/schedule complete works offline and syncs when reconnected
- **Accessibility** — Atkinson Hyperlegible font, 20px base size, high-contrast colours, large tap targets

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

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash **Raspberry Pi OS with Desktop** to your SD card. In the imager's advanced options you can enable SSH for headless setup. Leave WiFi blank — end users connect via the in-app WiFi setup page once the Pi is running.

### 2. Boot and run the setup script

SSH in (or open a terminal on the Pi) and run:

```bash
curl -sSL https://raw.githubusercontent.com/skinnydesign/dementia-client/main/setup.sh | sudo bash
```

Or if you've already cloned the repo:

```bash
sudo bash setup.sh
```

To use the lighter **Cog** browser instead of Chromium (see [Kiosk Browser](#kiosk-browser-chromium-or-cog)):

```bash
sudo KIOSK_BROWSER=cog bash setup.sh
```

The script will ask for your `API_BASE_URL` and `SECRET_KEY`, then handle everything:

- Installs all system dependencies
- Clones the repo and sets up a Python virtual environment
- Writes the `.env` file
- Configures passwordless sudo for WiFi commands
- Creates and enables the systemd service
- Enables desktop auto-login
- Configures the kiosk browser (Chromium by default, or Cog) to launch on boot
- Disables screen blanking

When it finishes, reboot:

```bash
sudo reboot
```

The Pi will boot straight into the kiosk display.

### Kiosk Browser (Chromium or Cog)

The display can run in either of two browsers. Both open full screen with no address bar or tabs.

| Browser | Memory | Notes |
|---|---|---|
| **Chromium** (default) | Higher (~300–500MB) | The original, well-tested setup |
| **Cog** (WPE WebKit) | Roughly half of Chromium | Made for embedded kiosk screens; lets cheaper low-RAM Pis (e.g. Pi 5 1GB) run the display |

Switch between them at any time on the Pi (Raspberry Pi OS Bookworm or later):

```bash
cd ~/dementia-client
git pull

sudo ./kiosk-browser.sh cog        # switch to Cog (installs it on first use)
sudo ./kiosk-browser.sh chromium   # switch back to Chromium
sudo ./kiosk-browser.sh status     # show which browser is configured

sudo reboot                        # the change applies after a reboot
```

The script rewrites `~/.config/labwc/autostart` and records the choice in `~/.config/dementia-kiosk-browser`. Switching back is instant because Cog stays installed.

**Checklist when trying Cog:**

- [ ] **Alarm chime plays.** This is the most important check. Make a schedule item due and listen for the sound. Cog uses GStreamer for audio, and the script installs the plugins it needs.
- [ ] **Opens full screen** with no window border. If it opens in a window, note the output of `cog --version`.
- [ ] **Touch works** on todo rows, buttons and the on-screen keyboard.
- [ ] **Alert banner, camera badge and carer button** appear as normal.
- [ ] **Memory use** is lower: compare `free -m` under each browser.

If anything on the checklist fails, run `sudo ./kiosk-browser.sh chromium` and reboot.

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
│   ├── css/
│   │   ├── style.css         # Animations and theme overrides (layout is Tailwind)
│   │   ├── tailwind.src.css  # Tailwind source (@tailwind directives)
│   │   ├── tailwind.css      # Compiled Tailwind output — committed, built by build-css.sh
│   │   └── fonts.css         # @font-face declarations
│   ├── fonts/          # Self-hosted font files (Atkinson Hyperlegible, DM Sans, JetBrains Mono)
│   └── js/app.js       # Flash message auto-dismiss
├── templates/
│   ├── base.html       # Shared layout, schedule alarm, alert banner
│   ├── login.html      # Sign in page (includes WiFi setup link)
│   ├── wifi_setup.html # WiFi setup (no login required)
│   ├── dashboard.html  # Main kiosk display page
│   ├── index.html      # Settings page (WiFi, account, display)
│   └── widgets/
│       ├── clock.html
│       ├── todos.html
│       ├── schedule.html
│       └── ical.html
├── tests/
│   ├── conftest.py     # Pytest fixtures
│   ├── test_db.py      # Database function tests
│   ├── test_routes.py  # Flask route tests
│   └── test_sync.py    # Sync logic tests
├── data/               # SQLite database (git-ignored)
├── tailwind.config.js  # Tailwind theme (fonts, colours) and files to scan for classes
├── build-css.sh        # Builds static/css/tailwind.css
├── kiosk-browser.sh    # Pi only: switch kiosk browser between Chromium and Cog
├── setup.sh            # Raspberry Pi installer
├── docker-compose.yml
├── Dockerfile
├── pytest.ini
└── requirements.txt
```

---

## Styling (Tailwind CSS)

Tailwind is compiled **once** into `static/css/tailwind.css`, which is committed to the repo. The browser just loads a small static stylesheet; nothing is compiled on the device and no CDN is used. The Pi doesn't need Node or any build step: `git pull` brings the updated CSS.

After adding or changing Tailwind classes in a template or JS file, rebuild and commit the CSS:

```bash
./build-css.sh           # one-off build
./build-css.sh --watch   # rebuild automatically while you work
```

The first run downloads the Tailwind v3.4.17 standalone CLI into `bin/` (git-ignored). It needs no Node.js and works on macOS and Linux, on both Intel and ARM. Theme settings (fonts, colours) live in `tailwind.config.js`.

> **Note:** Write class names out in full, e.g. `bg-amber-500`. Tailwind only includes classes it can find as complete words in the templates and JS, so a class built in code like `` `bg-${colour}-500` `` will be missing from the CSS.

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

## Testing

A full test suite (113 tests) covers the database layer, all Flask routes, and the background sync logic. Tests run against a temporary SQLite database with all HTTP calls mocked — no Laravel server needed.

```bash
pip install pytest
python3 -m pytest
```

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
