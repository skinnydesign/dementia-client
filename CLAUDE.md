# Flask Todo Client — CLAUDE.md

## What this project is
A Python/Flask dashboard that acts as a frontend UI for the **dementia** Laravel API backend. Flask is purely a UI layer — all data lives in Laravel. Runs at `http://python-client.test`.

## Related Projects
- **API backend**: Laravel app in `../dementia` (or `dementia` project directory)
- Both services share the `proxy` Docker network (managed by Traefik)
- Laravel is reachable inside Docker as `http://dementia-nginx-1/api`

## Docker Setup
- Runs via `docker-compose.yml` using gunicorn on port 8000
- Uses `--reload` flag so Python code changes apply without manual restart
- Three volume mounts — changes to these apply immediately:
  - `./app` → `/app` (Python source)
  - `./templates` → `/app/templates` (Jinja2 templates)
  - `./static` → `/app/static` (CSS/JS)
- `./data` → `/data` for persistent config (`DATA_DIR=/data`)
- External `proxy` network must exist before starting: `docker network create proxy`

## Entry Point
- `app/app.py` — single-file flat Flask app (not blueprints)
- Gunicorn runs `app:app` from the `/app` workdir
- `app/__init__.py` exists but is an incomplete blueprinted version — **not used**

## Auth
- Login via `POST /api/token` (Sanctum) with `{email, password}`
- Response returns `token`, `expires_at`, and `user` object
- Token stored in Flask session as `session["api_token"]`
- Logout via `DELETE /api/token`
- All protected routes use `@login_required` decorator

## Laravel API Endpoints Used
| Flask route | Laravel route | Notes |
|---|---|---|
| `GET /api/todos` | `GET /api/apiTodos` | Returns paginated — extract `data.data` |
| `POST /api/todos` | `POST /api/apiTodos` | Field is `todo` not `title` |
| `PUT /api/todos/<id>/complete` | `PUT /api/apiTodos/<id>/complete` | Dedicated complete endpoint |
| `DELETE /api/token` | `DELETE /api/token` | Logout/revoke |

## Known Quirks
- Laravel resource is named `apiTodos` (not `todos`) — all API calls use this path
- Todo field is `todo` (not `title`), completion is `completed` boolean
- `GET /api/apiTodos` returns paginated by default — actual items are at `data.data`
- Delete is intentionally removed from the UI — todos can only be marked complete
- WiFi scan/connect routes exist in the app but don't work inside Docker (graceful failure)
- `app/__init__.py` references blueprints/modules that don't exist — ignore it

## Templates
- `templates/base.html` — shared layout with sidebar, requires `nav` and `user` context vars
- `templates/login.html` — unauthenticated login page
- `templates/todos.html` — main todos UI, loads data via JS fetch to `/api/todos`
- `templates/index.html` — settings page (WiFi, account, module visibility)
- The `_icon()` macro must be defined at the **top** of `base.html` (before use) — Jinja2 macros follow execution order

## Context Processor
`app/app.py` injects `nav` and `user` into all templates:
- `nav` — list of sidebar modules, currently just `[{slug: "todos", label: "Todos", icon: "check-square"}]`
- `user` — `{name, email}` pulled from session

## Config
- `API_BASE_URL` — set in `.env`, read as default in `DEFAULT_CONFIG`
- Config persisted to `/data/.flask_todo_config.json` (survives container restarts)
- `SECRET_KEY` — set in `.env`
