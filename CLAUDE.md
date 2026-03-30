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
  base.html     — shared layout (no sidebar), settings cog fixed bottom-right
  login.html    — unauthenticated login page (has WiFi setup link)
  wifi_setup.html — public WiFi scan/connect page
  todos.html    — main display (todos, schedule, iCal panels)
  index.html    — settings page (module visibility, account)
  widgets/
    todos.html    — incomplete todos widget
    schedule.html — due schedule items widget
    ical.html     — upcoming iCal events widget
static/
  css/style.css — custom animations (alarmFlash, alarmPulseIcon, alarmShake)
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

## Entry Point
- `app/app.py` — single-file flat Flask app (not blueprints)
- Gunicorn runs `app:app` from the `/app` workdir
- On startup: `db.init_db()` creates tables, `sync.start()` launches background thread

## Auth
- Login via `POST /api/token` (Sanctum) with `{email, password}`
- Response returns `token`, `expires_at`, and `user` object
- Token stored in Flask session as `session["api_token"]`; also stored in SQLite `sync_state` table for background thread access
- On login: stores token + base_url in DB, triggers immediate sync via `sync.trigger()`
- Logout via `DELETE /api/token`, clears session and SQLite sync_state
- All protected routes use `@login_required` decorator

## SQLite Database (`app/db.py`)
Database lives at `$DATA_DIR/app.sqlite` (default `/data/app.sqlite`). WAL mode for concurrent access.

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
- `_push_queue()` — pushes pending `complete_todo` and `complete_schedule` actions to Laravel
- Token and base_url read from SQLite `sync_state` (set during login, not from Flask session)

## Flask Routes
| Route | Auth | Purpose |
|---|---|---|
| `GET /` | required | Redirects to `/todos` |
| `GET /login` | public | Login form |
| `POST /login` | public | Authenticate, store token, trigger sync |
| `POST /logout` | required | Clear session + sync_state |
| `GET /todos` | required | Main display page |
| `GET /settings` | required | Module visibility settings |
| `GET /wifi-setup` | **public** | WiFi scan/connect (Pi only) |
| `GET /api/todos` | required | Serve todos from SQLite |
| `GET /api/schedule/due` | required | Serve due schedule items from SQLite |
| `POST /api/schedule/<id>/complete` | required | Mark done locally + enqueue push |
| `GET /api/alert` | required | Serve active alert from SQLite |
| `GET /api/ical` | required | Serve iCal events from SQLite |
| `POST /api/sync` | required | Force immediate sync |
| `GET /api/wifi/scan` | public | Scan WiFi networks (Pi only, fails gracefully in Docker) |
| `POST /api/wifi/connect` | public | Connect to WiFi (Pi only) |

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
| Fetch iCal settings | `GET /api/ical/settings` | Returns ical_url, ical_days |

## Schedule System
Schedule items have: `name`, `frequency` (daily/every_other_day/weekly), `day_of_week` (weekly only), `scheduled_time`, `last_completed_at`, `is_active`, `overdue_threshold` (nullable int, minutes after due time to flag as overdue).

The `is_due()` logic in `db.py` replicates Laravel's `Schedule::isDue()` exactly so offline detection works.

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

## Known Quirks
- Laravel todo resource is named `apiTodos` (not `todos`) — all API calls use this path
- Todo field is `todo` (not `title`), completion is `completed` boolean
- `GET /api/apiTodos` returns paginated — actual items are at `data.data`
- Delete is removed from the UI — todos can only be marked complete
- WiFi scan/connect uses `nmcli` and won't work inside Docker (graceful failure)
- Multiple gunicorn workers each run their own sync thread — WAL mode handles concurrent SQLite writes

## Config
- `API_BASE_URL` — set in `.env`, stored in SQLite `sync_state` after login
- `SECRET_KEY` — set in `.env`
- `DATA_DIR` — set in `.env` (default `/data`)
- See `.env.example` for template
