# Flask Todo Client

A Python/Flask dashboard that communicates with the Laravel Todo API.

## Features
- **Login** with Laravel credentials — validates subscription via API 402 response
- **Todos** — list, create, complete, edit, delete, history with date filtering
- **Settings / WiFi** — scan nearby networks, connect/disconnect via `nmcli`
- **Settings / Modules** — show or hide sections from the sidebar per-session
- **Scalable** — add new API modules and UI sections with minimal boilerplate

## Setup

```bash
# 1. Clone / copy files
cd flask-todo-client

# 2. Create virtualenv
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — set API_BASE_URL to your Laravel app

# 5. Run
python run.py
# Open http://localhost:5000
```

## Project Structure

```
flask-todo-client/
├── app/
│   ├── __init__.py          # App factory, blueprint registration
│   ├── config.py            # All config from environment
│   ├── api/
│   │   ├── client.py        # Central Laravel HTTP client
│   │   └── modules/
│   │       └── todos.py     # Todos API methods  ← add new API modules here
│   ├── blueprints/
│   │   ├── auth.py          # Login / logout
│   │   ├── dashboard.py     # Home screen
│   │   ├── settings.py      # WiFi + account + module visibility
│   │   └── todos.py         # Todo routes        ← add new blueprints here
│   ├── modules/
│   │   └── registry.py      # Module show/hide registry  ← register new modules here
│   └── wifi/
│       └── manager.py       # nmcli wrapper
├── static/css/app.css
├── static/js/app.js
├── templates/
│   ├── base.html            # Shared layout with sidebar
│   ├── auth/login.html
│   ├── dashboard/index.html
│   ├── settings/index.html
│   ├── todos/index.html
│   └── todos/history.html
├── requirements.txt
├── run.py
└── .env.example
```

## Adding a New Module (e.g. Notes)

1. **Register it** in `app/modules/registry.py` — add to `AVAILABLE_MODULES`
2. **Add it** to `.env`: `ENABLED_MODULES=todos,notes`
3. **Create API methods** in `app/api/modules/notes.py`
4. **Create blueprint** in `app/blueprints/notes.py`
5. **Register blueprint** in `app/__init__.py`
6. **Create templates** in `templates/notes/`

## WiFi Requirements

WiFi scanning requires `nmcli` (NetworkManager):

```bash
# Raspberry Pi / Ubuntu / Debian
sudo apt install network-manager

# The Flask process may need permission to run nmcli
# On Raspberry Pi, add the user to the netdev group:
sudo usermod -aG netdev $USER
```

On macOS/Windows development machines, mock data is returned automatically.
