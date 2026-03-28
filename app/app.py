"""
Flask Todo Manager — Laravel API Client
All data is cached locally in SQLite and synced from Laravel in the background.
"""

import json
import os
import platform
import subprocess
from datetime import datetime

import requests
from flask import (Flask, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from functools import wraps

import db
import sync

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-please")

CONFIG_FILE = os.path.join(
    os.environ.get("DATA_DIR", os.path.expanduser("~")), ".flask_todo_config.json"
)

# ─────────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────────

db.init_db()
sync.start()


# ─────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "api_base_url": os.environ.get("API_BASE_URL", "https://your-laravel-app.com/api"),
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()


def save_config(data):
    cfg = load_config()
    cfg.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ─────────────────────────────────────────────────────────────
#  TEMPLATE CONTEXT
# ─────────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    nav = [
        {"slug": "dashboard", "label": "Dashboard", "icon": "grid"},
        {"slug": "todos",     "label": "Todos",     "icon": "check-square"},
    ]
    user = {
        "name":  session.get("user_name", ""),
        "email": session.get("user_email", ""),
    }
    last_sync = db.get_state("last_sync")
    return {"nav": nav, "user": user, "last_sync": last_sync, "config": load_config()}


# ─────────────────────────────────────────────────────────────
#  AUTH DECORATOR
# ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("api_token"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────
#  LARAVEL API HELPERS  (used only for auth and direct writes)
# ─────────────────────────────────────────────────────────────

def api_headers():
    token = session.get("api_token", "")
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def api_url(path):
    base = load_config().get("api_base_url", "").rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _parse_json(r):
    try:
        return r.json()
    except Exception:
        return {"message": f"API returned non-JSON (HTTP {r.status_code}): {r.text[:200]}"}


def laravel_post(path, payload):
    try:
        r = requests.post(api_url(path), json=payload, headers=api_headers(), timeout=10)
        return r.status_code, _parse_json(r)
    except requests.exceptions.ConnectionError:
        return 503, {"message": "Cannot reach the API server."}
    except Exception as e:
        return 500, {"message": str(e)}


def laravel_put(path, payload):
    try:
        r = requests.put(api_url(path), json=payload, headers=api_headers(), timeout=10)
        return r.status_code, _parse_json(r)
    except Exception as e:
        return 500, {"message": str(e)}


# ─────────────────────────────────────────────────────────────
#  WIFI HELPERS
# ─────────────────────────────────────────────────────────────

def scan_wifi():
    OS = platform.system()
    networks = []
    try:
        if OS == "Linux":
            result = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE",
                 "dev", "wifi", "list", "--rescan", "yes"],
                capture_output=True, text=True, timeout=20
            )
            seen = set()
            for line in result.stdout.strip().splitlines():
                parts = line.split(":")
                if len(parts) >= 4:
                    ssid = parts[0].strip()
                    if not ssid or ssid in seen:
                        continue
                    seen.add(ssid)
                    sig = parts[1].strip()
                    networks.append({
                        "ssid": ssid, "signal": int(sig) if sig.isdigit() else 0,
                        "security": parts[2].strip() or "Open",
                        "in_use": parts[3].strip() == "*",
                        "bars": max(1, min(4, int(sig) // 25)) if sig.isdigit() else 1,
                    })
        elif OS == "Darwin":
            airport = ("/System/Library/PrivateFrameworks/Apple80211.framework"
                       "/Versions/Current/Resources/airport")
            result = subprocess.run([airport, "-s"],
                                    capture_output=True, text=True, timeout=15)
            for line in result.stdout.strip().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    sig = int(parts[2]) if parts[2].lstrip("-").isdigit() else -100
                    pct = max(0, min(100, 2 * (sig + 100)))
                    networks.append({
                        "ssid": parts[0], "signal": pct,
                        "security": parts[-1] if len(parts) > 5 else "Open",
                        "in_use": False,
                        "bars": max(1, min(4, pct // 25)),
                    })
        networks.sort(key=lambda x: x["signal"], reverse=True)
    except Exception as e:
        networks = [{"ssid": f"Scan error: {e}", "signal": 0,
                     "security": "", "in_use": False, "bars": 0, "error": True}]
    return networks


def connect_to_wifi(ssid, password=""):
    OS = platform.system()
    try:
        if OS == "Linux":
            cmd = ["nmcli", "dev", "wifi", "connect", ssid]
            if password:
                cmd += ["password", password]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            ok = "successfully" in r.stdout.lower()
            return ok, r.stdout.strip() or r.stderr.strip()
        elif OS == "Darwin":
            r = subprocess.run(
                ["networksetup", "-setairportnetwork", "en0", ssid, password],
                capture_output=True, text=True, timeout=30)
            return r.returncode == 0, "Connected" if r.returncode == 0 else r.stderr
    except Exception as e:
        return False, str(e)
    return False, "Unsupported OS"


# ─────────────────────────────────────────────────────────────
#  ROUTES — PUBLIC
# ─────────────────────────────────────────────────────────────

@app.route("/wifi-setup")
def wifi_setup():
    return render_template("wifi_setup.html")


@app.route("/api/wifi/scan")
def wifi_scan():
    return jsonify(scan_wifi())


@app.route("/api/wifi/connect", methods=["POST"])
def wifi_connect():
    data     = request.get_json()
    ssid     = data.get("ssid", "")
    password = data.get("password", "")
    if not ssid:
        return jsonify({"ok": False, "message": "SSID required"}), 400
    ok, msg = connect_to_wifi(ssid, password)
    return jsonify({"ok": ok, "message": msg})


# ─────────────────────────────────────────────────────────────
#  ROUTES — AUTH
# ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    if session.get("api_token"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("api_token"):
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            error = "Email and password are required."
        else:
            status, data = laravel_post("token", {"email": email, "password": password})
            if status == 200:
                token = (data.get("token") or data.get("access_token") or
                         data.get("data", {}).get("token", ""))
                user  = data.get("user", data.get("data", {}).get("user", data))

                if not token:
                    error = "Login succeeded but no token was returned."
                else:
                    session["api_token"]  = token
                    session["user_name"]  = user.get("name", email)
                    session["user_email"] = user.get("email", email)

                    # Store credentials for background sync
                    db.set_state("api_token",   token)
                    db.set_state("api_base_url", load_config().get("api_base_url", ""))

                    # Kick off an immediate sync so the UI has data right away
                    sync.trigger()

                    return redirect(url_for("dashboard"))
            elif status in (401, 422):
                error = data.get("message", "Invalid credentials.")
            elif status == 503:
                error = data.get("message", "Cannot reach server.")
            else:
                error = data.get("message", f"Unexpected error (HTTP {status}).")

    return render_template("login.html", error=error)


@app.route("/logout", methods=["GET", "POST"])
def logout():
    token = session.get("api_token")
    if token:
        try:
            requests.delete(api_url("token"), headers=api_headers(), timeout=5)
        except Exception:
            pass
    db.set_state("api_token", None)
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ─────────────────────────────────────────────────────────────
#  ROUTES — SETTINGS
# ─────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    cfg = load_config()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save_api":
            save_config({"api_base_url": request.form.get("api_base_url", "").strip()})
            db.set_state("api_base_url", load_config().get("api_base_url", ""))
            flash("API configuration saved.", "success")
        return redirect(url_for("settings"))

    hidden    = session.get("hidden_modules", [])
    available = [
        {"slug": "todos", "label": "Todos", "description": "Manage your todo items",
         "icon": "check-square"},
    ]
    return render_template("index.html", config=cfg, current_wifi=None,
                           available_modules=available, config_enabled=["todos"],
                           hidden_modules=hidden)


@app.route("/settings/wifi/disconnect", methods=["POST"])
@login_required
def wifi_disconnect():
    flash("Disconnect not supported in this environment.", "warning")
    return redirect(url_for("settings"))


@app.route("/settings/wifi/connect", methods=["POST"])
@login_required
def wifi_connect_form():
    ssid     = request.form.get("ssid", "")
    password = request.form.get("password", "")
    if not ssid:
        flash("SSID required.", "error")
        return redirect(url_for("settings"))
    ok, msg = connect_to_wifi(ssid, password)
    flash(msg or ("Connected." if ok else "Connection failed."), "success" if ok else "error")
    return redirect(url_for("settings"))


@app.route("/settings/toggle-module", methods=["POST"])
@login_required
def toggle_module():
    slug   = request.form.get("slug", "")
    action = request.form.get("action", "hide")
    hidden = session.get("hidden_modules", [])
    if action == "hide" and slug not in hidden:
        hidden.append(slug)
    elif action == "show" and slug in hidden:
        hidden.remove(slug)
    session["hidden_modules"] = hidden
    return redirect(url_for("settings"))


@app.route("/api/sync", methods=["POST"])
@login_required
def api_force_sync():
    """Trigger an immediate sync on demand."""
    sync.trigger()
    return jsonify({"ok": True, "message": "Sync triggered."})


# ─────────────────────────────────────────────────────────────
#  ROUTES — PAGES
# ─────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    layout = db.get_layout()
    return render_template("dashboard.html", layout=layout)


@app.route("/todos")
@login_required
def todos():
    return render_template("todos.html")


# ─────────────────────────────────────────────────────────────
#  ROUTES — DATA API  (all served from local SQLite)
# ─────────────────────────────────────────────────────────────

@app.route("/api/todos")
@login_required
def api_todos():
    return jsonify({"ok": True, "todos": db.get_todos()})


@app.route("/api/todos", methods=["POST"])
@login_required
def api_create_todo():
    payload      = request.get_json()
    status, data = laravel_post("apiTodos", payload)
    if status in (200, 201):
        sync.trigger()   # refresh local cache
        return jsonify({"ok": True, "todo": data.get("data", data)})
    return jsonify({"ok": False, "message": data.get("message", "Create failed")}), status


@app.route("/api/todos/<int:todo_id>/complete", methods=["PUT"])
@login_required
def api_complete_todo(todo_id):
    # Update locally immediately so the UI responds instantly
    db.complete_todo_locally(todo_id)
    # Queue the write for when we're next online
    db.enqueue("complete_todo", {"id": todo_id})
    # Also try right now in case we're online
    try:
        laravel_put(f"apiTodos/{todo_id}/complete", {})
        db.dequeue_by_action("complete_todo", todo_id)
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/schedule/due")
@login_required
def api_schedule_due():
    items = db.get_due_items()
    return jsonify({
        "ok":    True,
        "items": [
            {
                "id":             i["id"],
                "name":           i["name"],
                "frequency":      _frequency_label(i),
                "scheduled_time": i["scheduled_time"][:5],
            }
            for i in items
        ]
    })


@app.route("/api/schedule/<int:item_id>/complete", methods=["PUT"])
@login_required
def api_schedule_complete(item_id):
    db.complete_schedule_locally(item_id)
    db.enqueue("complete_schedule", {"id": item_id})
    try:
        laravel_put(f"schedule/{item_id}/complete", {})
        db.dequeue_by_action("complete_schedule", item_id)
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/alert")
@login_required
def api_alert():
    alert = db.get_alert()
    return jsonify({"ok": True, "alert": alert})


@app.route("/api/ical")
@login_required
def api_ical():
    events    = db.get_ical_events()
    ical_days = int(db.get_state("ical_days") or 7)
    return jsonify({"ok": True, "events": [
        {
            "summary":  e["summary"],
            "date":     e["date"],
            "end":      e["end_date"],
            "time":     e["time"],
            "end_time": e["end_time"],
            "location": e["location"],
        }
        for e in events
    ], "ical_days": ical_days})


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _frequency_label(item: dict) -> str:
    freq = item.get("frequency", "")
    if freq == "daily":
        return "Daily"
    if freq == "every_other_day":
        return "Every other day"
    if freq == "weekly":
        return f"Weekly on {(item.get('day_of_week') or '').capitalize()}"
    return freq


# ─────────────────────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
