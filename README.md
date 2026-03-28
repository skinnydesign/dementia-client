# Dementia Client

A Python/Flask dashboard designed to run on a Raspberry Pi as a always-on display. It connects to the **dementia** Laravel API and caches all data locally in SQLite so the display keeps working even without an internet connection.

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
- Docker & Docker Compose (recommended), **or** a plain Python environment
- A running instance of the **dementia** Laravel API

---

## Quick Start (Docker — recommended)

```bash
# 1. Clone the repo
git clone https://github.com/skinnydesign/dementia-client.git
cd dementia-client

# 2. Create environment file
cp .env.example .env
# Edit .env — set API_BASE_URL and SECRET_KEY

# 3. Start
docker compose up -d

# Open http://localhost:8000
```

---

## Quick Start (Raspberry Pi — without Docker)

```bash
# 1. Clone the repo
git clone https://github.com/skinnydesign/dementia-client.git
cd dementia-client

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create environment file
cp .env.example .env
# Edit .env — set API_BASE_URL and SECRET_KEY

# 5. Run
cd app
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

To run on boot, add a systemd service or use `cron @reboot`.

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
| `DATA_DIR` | Where SQLite database and config are stored (default: `~`) |

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
│   ├── login.html      # Sign in page
│   ├── wifi_setup.html # WiFi setup (no login required)
│   ├── dashboard.html  # Widget layout page
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

## WiFi (Raspberry Pi)

WiFi scanning uses `nmcli`. Install NetworkManager if it isn't present:

```bash
sudo apt install network-manager

# Allow the app user to run nmcli without sudo
sudo usermod -aG netdev $USER
```

The WiFi setup page is available at `/wifi-setup` **without logging in**, so users can connect the device to their network before signing in.

---

## Laravel API

This client connects to the **dementia** Laravel app. The following API endpoints are used:

| Endpoint | Purpose |
|---|---|
| `POST /api/token` | Login |
| `DELETE /api/token` | Logout |
| `GET /api/apiTodos` | Fetch todos |
| `PUT /api/apiTodos/{id}/complete` | Complete a todo |
| `GET /api/schedule` | Fetch schedule items |
| `PUT /api/schedule/{id}/complete` | Complete a schedule item |
| `GET /api/ical` | Fetch iCal settings (URL + days) |
| `GET /api/alert` | Fetch current active alert |
| `GET /api/layout` | Fetch dashboard widget layout |
