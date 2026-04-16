# Flask Todo Client — CLAUDE.md

## What this project is
A Python/Flask dashboard that acts as a frontend display (Raspberry Pi kiosk) for the **dementia** Laravel API backend. Runs at `http://python-client.test`. Uses SQLite local caching for offline support and reduced API calls — all reads serve from local DB, writes update locally then sync to Laravel.

## Related Projects
- **API backend**: Laravel app in `../dementia` (or `dementia` project directory)
- Both services share the `proxy` Docker network (managed by Traefik)
- Laravel is reachable inside Docker as `http://dementia-nginx-1/api`

## Project Structure
```
app/
  app.py        — single-file flat Flask app (all routes here)
  db.py         — SQLite operations: init, reads, writes, sync queue
  sync.py       — background thread: polls Laravel every 5 min, iCal every 30 min
templates/
  base.html     — shared layout, settings cog (or back arrow on settings page) fixed bottom-right
  login.html    — unauthenticated login page (has WiFi setup link)
  wifi_setup.html — public WiFi scan/connect page
  dashboard.html — main kiosk display (todos, schedule, iCal panels)
  index.html    — settings page (WiFi, account, display)
  widgets/
    todos.html    — incomplete todos widget (full-row tap to complete)
    schedule.html — due schedule items widget
    ical.html     — upcoming iCal events widget
    clock.html    — clock/date widget
static/
  css/
    style.css   — custom animations (alarmFlash, alarmPulseIcon, alarmShake)
    fonts.css   — @font-face declarations for Atkinson Hyperlegible, DM Sans, JetBrains Mono
  fonts/        — self-hosted font files (Atkinson Hyperlegible, DM Sans, JetBrains Mono)
tests/
  conftest.py   — pytest fixtures (temp DB, patched sync.start, Flask test client)
  test_db.py    — unit tests for all db.py functions
  test_routes.py — Flask route tests (auth, API endpoints, page rendering)
  test_sync.py  — sync pull/push logic tests (all HTTP calls mocked)
data/           — persistent SQLite DB (git-ignored, survives container restarts)
```

**Deleted legacy files** (no longer present): root-level `app.py`, `auth.py`, `client.py`, `manager.py`, `registry.py`, `run.py`, `settings.py`, `todos.py`, `requirements 2.txt`, `app/__init__.py`

## Docker Setup
- Runs via `docker-compose.yml` using gunicorn on port 8000
- Uses `--reload` flag so Python code changes apply without manual restart
- Volume mounts — changes apply immediately:
  - `./app` → `/app` (Python source)
  - `./templates` → `/app/templates` (Jinja2 templates)
  - `./static` → `/app/static` (CSS/JS)
  - `./data` → `/data` (SQLite DB, `DATA_DIR=/data`)
- External `proxy` network must exist before starting: `docker network create proxy`
- **Note**: `app/templates/` and `app/static/` are empty Docker mount-point directories on the host — the real files live at the root-level `templates/` and `static/`

## Entry Point
- `app/app.py` — single-file flat Flask app (not blueprints)
- Gunicorn runs `app:app` from the `/app` workdir
- On startup: `db.init_db()` creates tables, `sync.start()` launches background thread

## Auth
- Login via `POST /api/token` (Sanctum) with `{email, password}` **or** `{username, password}`
- The login form has a single `login` field; the app detects `@` in the value to decide whether to send `email` or `username` to Laravel
- Response returns `token`, `expires_at`, and `user` object
- Token stored in Flask session as `session["api_token"]`; also stored in SQLite `sync_state` table for background thread access
- On login: stores token + base_url in DB, triggers immediate sync via `sync.trigger()`
- Logout via `DELETE /api/token`, clears session and SQLite sync_state
- All protected routes use `@login_required` decorator

## SQLite Database (`app/db.py`)
Database lives at `$DATA_DIR/control.db` (default `~/control.db`). WAL mode for concurrent access.

Tables:
| Table | Purpose |
|---|---|
| `todos` | Cached todo items from Laravel |
| `schedule_items` | Cached schedule items (name, frequency, scheduled_time, etc.) |
| `schedule_completions` | Completion history (schedule_id, completed_at) |
| `ical_events` | Parsed iCal events (title, start, end, time, end_time) |
| `alert_cache` | Active alert message + expiry |
| `layout_cache` | Which widgets are visible |
| `sync_queue` | Pending writes to push to Laravel (action, payload JSON) |
| `sync_state` | Stores `api_token` and `api_base_url` for background thread |
| `carer_visits` | Local record of carer arrivals/departures (synced to Laravel) |

Key functions:
- `init_db()` — creates all tables if missing
- `is_due(item)` — replicates Laravel's `isDue()` for daily/every_other_day/weekly
- `get_due_items()` — returns active schedule items that are currently due
- `complete_schedule_locally(id)` — updates `last_completed_at` AND inserts completion record
- `upsert_completions(schedule_id, completions)` — syncs completion history from Laravel
- `enqueue(action, payload)` — adds item to sync_queue
- `dequeue_by_action(action)` — fetches pending items of a given action type

## Background Sync (`app/sync.py`)
- `start()` — launches daemon thread on app startup
- `trigger()` — runs immediate one-shot sync (called after login)
- Main sync every **5 minutes**: todos, schedule items, completions, alert, layout
- iCal sync every **30 minutes**: fetches iCal settings then parses feed
- `_push_queue()` — pushes pending `complete_todo`, `complete_schedule`, `carer_arrive`, and `carer_leave` actions to Laravel
- Token and base_url read from SQLite `sync_state` (set during login, not from Flask session)

## Flask Routes
| Route | Auth | Purpose |
|---|---|---|
| `GET /` | required | Redirects to `/dashboard` |
| `GET /login` | public | Login form |
| `POST /login` | public | Authenticate, store token, trigger sync |
| `POST /logout` | required | Clear session + sync_state |
| `GET /dashboard` | required | Main kiosk display page |
| `GET /settings` | required | WiFi, account, display settings |
| `GET /wifi-setup` | **public** | WiFi scan/connect (Pi only) |
| `GET /api/todos` | required | Serve todos from SQLite |
| `GET /api/schedule/due` | required | Serve due schedule items from SQLite |
| `PUT /api/schedule/<id>/complete` | required | Mark done locally + enqueue push |
| `GET /api/alert` | required | Serve active alert from SQLite |
| `GET /api/ical` | required | Serve iCal events from SQLite |
| `POST /api/sync` | required | Force immediate sync |
| `GET /api/wifi/scan` | public | Scan WiFi networks (Pi only, fails gracefully in Docker) |
| `POST /api/wifi/connect` | public | Connect to WiFi — **blocking**, returns only when fully connected or failed |
| `GET /api/wifi/verify` | public | Check if the configured API URL is reachable (used post-connect) |
| `GET /api/carer/status` | required | Returns active carer visit or null |
| `POST /api/carer/arrive` | required | Record carer arrival (name required) |
| `POST /api/carer/leave` | required | Record carer departure |

## Laravel API Endpoints Used
| Purpose | Laravel route | Notes |
|---|---|---|
| Auth login | `POST /api/token` | Returns `token`, `expires_at`, `user` |
| Auth logout | `DELETE /api/token` | |
| Fetch todos | `GET /api/apiTodos` | Paginated — extract `data.data` |
| Complete todo | `PUT /api/apiTodos/<id>/complete` | |
| Fetch schedule | `GET /api/schedule` | Returns items with last 20 completions eager-loaded |
| Complete schedule | `PUT /api/schedule/<id>/complete` | Creates completion record + updates last_completed_at |
| Fetch alert | `GET /api/alert` | Returns active alert or empty |
| Fetch layout | `GET /api/layout` | Module visibility settings |
| Fetch iCal settings | `GET /api/ical` | Returns ical_url, ical_days |

## Schedule System
Schedule items have: `name`, `frequency` (daily/every_other_day/weekly), `day_of_week` (weekly only), `scheduled_time`, `last_completed_at`, `is_active`, `overdue_threshold` (nullable int, minutes after due time to flag as overdue).

The `is_due()` logic in `db.py` replicates Laravel's `Schedule::isDue()` exactly so offline detection works.

**Suspend/pause feature**: Schedules can be paused via the Laravel admin UI (`/schedule/settings`). The Laravel `ScheduleController` returns `suspended: true` with an empty `items` list when paused; `sync.py` stores this in `sync_state` as `schedules_suspended`. The schedule widget displays "Schedules paused" instead of the alarm overlay. Suspensions can be indefinite or until a specific date (auto-cleared server-side when the date passes).

**Alarm behaviour** (in `base.html` JS):
- `checkSchedule()` polls `/api/schedule/due` every 60s
- On due items: full-screen amber overlay with bell icon and item name, plays Web Audio chime (C-E-G-C ascending)
- `sessionStorage` tracks alerted IDs to prevent repeat triggers until item is completed and becomes due again
- "MARK ALL DONE" marks all due items complete; "Remind me again later" dismisses for the session

## Alert System
- Admin sets alert message + duration in Laravel UI (`/settings/alert`)
- `checkAlert()` in `base.html` polls `/api/alert` every 60s
- Displayed as amber banner at top, auto-dismisses when expired, has DISMISS button

## iCal Events
- Settings (URL + days ahead) stored in Laravel `user_settings`
- Background sync fetches and parses feed using `icalendar` Python library
- Timezone-aware datetimes converted to local time before storage
- Timed events show time (e.g. "27 Mar 14:30"); all-day events show date only

## Carer Visit System
- Carer presses a button (fixed bottom-left in `base.html`) to check in/out
- Check-in shows a modal to enter their name; check-out confirms departure
- Visit stored locally in `carer_visits` table, then synced to Laravel via `POST /api/carer-visits` and `PUT /api/carer-visits/{id}/leave`
- Laravel `CarerVisitHistory` Livewire page at `/carer-visits` shows full history with search and date filter

## Accessibility / UI
The UI is designed for users with dementia and age-related sight impairment:
- **Font**: Atkinson Hyperlegible (Braille Institute) as primary sans-serif, DM Sans as fallback; JetBrains Mono for UI labels and timestamps only
- **Base font size**: 20px default (adjustable in settings via localStorage)
- **Body**: `font-semibold`, `tracking-[0.02em]` globally
- **Colours**: surface `#161616`, panel `#1e1e1e`, raised `#252525`; primary text `#E8E6E3`; secondary text `#aaaaaa` (~6:1 contrast); item dividers `#333333`
- **Todo items**: full-row tap target (click anywhere on row to complete); 24px checkbox
- **Settings page**: bottom-right button shows a back arrow (→ `/dashboard`) when on settings, gear icon on all other pages

## Testing
Run the full test suite (91 tests, ~0.7s) from the project root:
```bash
python3 -m pytest
```
- `tests/conftest.py` — temp SQLite DB, sync thread patched out, Flask test client fixtures
- `tests/test_db.py` — all database functions including `is_due` logic for all frequency types
- `tests/test_routes.py` — every route: auth flow, API endpoints, page rendering, offline behaviour
- `tests/test_sync.py` — pull/push helpers with mocked HTTP; full `_run` cycle

Tests run against the host Python (3.9+). The `from __future__ import annotations` import in `db.py` ensures type hints are compatible with Python 3.9.

## Raspberry Pi Deployment (`setup.sh`)
- Run once on a fresh Raspberry Pi OS (Bookworm) install: `sudo bash setup.sh`
- Prompts for `API_BASE_URL` and optional `SECRET_KEY` (auto-generated if blank)
- Auto-detects the real username via `$SUDO_USER`
- Detects `chromium` vs `chromium-browser` package name (Bookworm vs Bullseye)
- Clones repo to `~/dementia-client`, creates venv, installs requirements
- Writes `.env`, creates systemd service (`dementia-client`), enables auto-login
- **Kiosk autostart (Bookworm/labwc)**: writes `~/.config/labwc/autostart` — a bash script that runs `chromium --kiosk http://localhost:8000 &` after a 5s delay
- **Kiosk autostart (Bullseye/LXDE)**: writes `/etc/xdg/lxsession/LXDE-pi/autostart`
- Disables screen blanking via `consoleblank=0` in `/boot/firmware/cmdline.txt`
- WiFi is configured through the in-app `/wifi-setup` page — do not use FullPageOS or other kiosk OSes as they require WiFi to be pre-configured before deployment
- Sudoers entry at `/etc/sudoers.d/dementia-wifi` grants passwordless `wpa_cli`, `iwgetid`, and `nmcli` to the install user

## Known Quirks
- Laravel todo resource is named `apiTodos` (not `todos`) — all API calls use this path
- Todo field is `todo` (not `title`), completion is `completed` boolean
- `GET /api/apiTodos` returns paginated — actual items are at `data.data`
- Delete is removed from the UI — todos can only be marked complete
- WiFi scan/connect uses **`nmcli`** on Raspberry Pi OS Bookworm (NetworkManager) and falls back to `wpa_cli`/`iwgetid` on older installs — detected at runtime via `systemctl is-active NetworkManager`; won't work inside Docker (graceful failure)
- `nmcli` is called via `sudo` because gunicorn runs as a service (not a console session) and PolicyKit would otherwise block NetworkManager access; `wpa_cli` likewise requires `sudo`
- `POST /api/wifi/connect` is a **blocking** endpoint — it waits up to 30 s for the full connection (WPA handshake + DHCP + IP assignment) before returning, so the frontend knows the Pi is genuinely online before showing "Connected"
- Wrong password detection: nmcli path parses the error output; wpa_cli path polls `list_networks` for the `TEMP-DISABLED` flag
- Multiple gunicorn workers each run their own sync thread — WAL mode handles concurrent SQLite writes
- DB filename is `control.db` (not `app.sqlite` as earlier versions used)
- `app/templates/` and `app/static/` on the host are empty Docker mount-point directories — tests override `template_folder` and `static_folder` to point at the real root-level directories

## Config
- `API_BASE_URL` — set in `.env`, stored in SQLite `sync_state` after login
- `SECRET_KEY` — set in `.env`
- `DATA_DIR` — set in `.env` (default `/data` in Docker, `~` on bare Pi)
- See `.env.example` for template
