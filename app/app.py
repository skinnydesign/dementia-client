"""
Flask Todo Manager — Laravel API Client
"""

import json
import os
import platform
import subprocess
import threading
from datetime import date, datetime, timedelta, timezone

import requests
from icalendar import Calendar
from flask import (Flask, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-please")

CONFIG_FILE = os.path.join(os.environ.get("DATA_DIR", os.path.expanduser("~")), ".flask_todo_config.json")

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
        "name": session.get("user_name", ""),
        "email": session.get("user_email", ""),
    }
    return {"nav": nav, "user": user}


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
#  LARAVEL API HELPER
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
        return {"message": f"API returned non-JSON response (HTTP {r.status_code}): {r.text[:200]}"}


def laravel_get(path):
    try:
        r = requests.get(api_url(path), headers=api_headers(), timeout=10)
        return r.status_code, _parse_json(r)
    except requests.exceptions.ConnectionError:
        return 503, {"message": f"Cannot reach the API server at: {api_url(path)}"}
    except Exception as e:
        return 500, {"message": str(e)}


def laravel_post(path, payload):
    try:
        r = requests.post(api_url(path), json=payload, headers=api_headers(), timeout=10)
        return r.status_code, _parse_json(r)
    except requests.exceptions.ConnectionError:
        return 503, {"message": f"Cannot reach the API server at: {api_url(path)}"}
    except Exception as e:
        return 500, {"message": str(e)}


def laravel_put(path, payload):
    try:
        r = requests.put(api_url(path), json=payload, headers=api_headers(), timeout=10)
        return r.status_code, _parse_json(r)
    except Exception as e:
        return 500, {"message": str(e)}


def laravel_delete(path):
    try:
        r = requests.delete(api_url(path), headers=api_headers(), timeout=10)
        return r.status_code, {}
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
                        "ssid": ssid,
                        "signal": int(sig) if sig.isdigit() else 0,
                        "security": parts[2].strip() or "Open",
                        "connected": parts[3].strip() == "*",
                    })
        elif OS == "Windows":
            result = subprocess.run(
                ["netsh", "wlan", "show", "networks", "mode=bssid"],
                capture_output=True, text=True, timeout=15
            )
            cur = {}
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("SSID") and "BSSID" not in line:
                    if cur:
                        networks.append(cur)
                    cur = {"ssid": line.split(":", 1)[-1].strip(),
                           "signal": 0, "security": "WPA2", "connected": False}
                elif "Signal" in line and cur:
                    sig = line.split(":", 1)[-1].strip().replace("%", "")
                    cur["signal"] = int(sig) if sig.isdigit() else 0
                elif "Authentication" in line and cur:
                    cur["security"] = line.split(":", 1)[-1].strip()
            if cur:
                networks.append(cur)
        elif OS == "Darwin":
            airport = ("/System/Library/PrivateFrameworks/Apple80211.framework"
                       "/Versions/Current/Resources/airport")
            result = subprocess.run([airport, "-s"],
                                     capture_output=True, text=True, timeout=15)
            for line in result.stdout.strip().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    networks.append({
                        "ssid": parts[0],
                        "signal": int(parts[2]) if parts[2].lstrip("-").isdigit() else 0,
                        "security": parts[-1] if len(parts) > 5 else "Open",
                        "connected": False,
                    })
        networks.sort(key=lambda x: x["signal"], reverse=True)
    except FileNotFoundError:
        networks = [{"ssid": "nmcli not found — install NetworkManager",
                     "signal": 0, "security": "", "connected": False, "error": True}]
    except Exception as e:
        networks = [{"ssid": f"Scan error: {e}",
                     "signal": 0, "security": "", "connected": False, "error": True}]
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
        elif OS == "Windows":
            r = subprocess.run(
                ["netsh", "wlan", "connect", f"name={ssid}"],
                capture_output=True, text=True, timeout=30
            )
            return "completed" in r.stdout.lower(), r.stdout.strip()
        elif OS == "Darwin":
            r = subprocess.run(
                ["networksetup", "-setairportnetwork", "en0", ssid, password],
                capture_output=True, text=True, timeout=30
            )
            return r.returncode == 0, "Connected" if r.returncode == 0 else r.stderr
    except Exception as e:
        return False, str(e)
    return False, "Unsupported OS"


# ─────────────────────────────────────────────────────────────
#  ROUTES — SETTINGS (PUBLIC)
# ─────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
def settings():
    cfg = load_config()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save_api":
            save_config({"api_base_url": request.form.get("api_base_url", "").strip()})
            flash("API configuration saved.", "success")
        return redirect(url_for("settings"))
    hidden = session.get("hidden_modules", [])
    available = [
        {"slug": "todos", "label": "Todos", "description": "Manage your todo items", "icon": "check-square"},
    ]
    config_enabled = ["todos"]
    return render_template("index.html", config=cfg, current_wifi=None,
                           available_modules=available, config_enabled=config_enabled,
                           hidden_modules=hidden)


@app.route("/settings/wifi/disconnect", methods=["POST"])
def wifi_disconnect():
    flash("Disconnect not supported in this environment.", "warning")
    return redirect(url_for("settings"))


@app.route("/settings/wifi/connect", methods=["POST"])
def wifi_connect_form():
    ssid = request.form.get("ssid", "")
    password = request.form.get("password", "")
    if not ssid:
        flash("SSID required.", "error")
        return redirect(url_for("settings"))
    ok, msg = connect_to_wifi(ssid, password)
    flash(msg if msg else ("Connected." if ok else "Connection failed."), "success" if ok else "error")
    return redirect(url_for("settings"))


@app.route("/settings/toggle-module", methods=["POST"])
def toggle_module():
    slug = request.form.get("slug", "")
    action = request.form.get("action", "hide")
    hidden = session.get("hidden_modules", [])
    if action == "hide" and slug not in hidden:
        hidden.append(slug)
    elif action == "show" and slug in hidden:
        hidden.remove(slug)
    session["hidden_modules"] = hidden
    return redirect(url_for("settings"))


@app.route("/api/wifi/scan")
def wifi_scan():
    networks = scan_wifi()
    return jsonify(networks)


@app.route("/api/wifi/connect", methods=["POST"])
def wifi_connect():
    data = request.get_json()
    ssid = data.get("ssid", "")
    password = data.get("password", "")
    if not ssid:
        return jsonify({"ok": False, "message": "SSID required"}), 400
    ok, msg = connect_to_wifi(ssid, password)
    return jsonify({"ok": ok, "message": msg})


# ─────────────────────────────────────────────────────────────
#  ROUTES — WIFI SETUP (public — no login required)
# ─────────────────────────────────────────────────────────────

@app.route("/wifi-setup")
def wifi_setup():
    return render_template("wifi_setup.html")


# ─────────────────────────────────────────────────────────────
#  ROUTES — AUTH
# ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    if session.get("api_token"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    status, data = laravel_get("layout")
    layout = data.get("layout") or {} if status == 200 else {}
    return render_template("dashboard.html", layout=layout)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("api_token"):
        return redirect(url_for("todos"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            error = "Email and password are required."
        else:
            status, data = laravel_post("token", {"email": email, "password": password})
            if status == 200:
                token = (data.get("token") or data.get("access_token") or
                         data.get("data", {}).get("token", ""))
                user = data.get("user", data.get("data", {}).get("user", data))

                if not token:
                    error = "Login succeeded but no token was returned. Check your Laravel API."
                else:
                    session["api_token"] = token
                    session["user_name"] = user.get("name", email)
                    session["user_email"] = user.get("email", email)

                    # Subscription check
                    subscribed = bool(
                        user.get("subscribed") or
                        user.get("is_subscribed") or
                        user.get("subscription_status") == "active"
                    )
                    plan = (user.get("plan") or user.get("subscription_plan") or
                            (user.get("subscription") or {}).get("plan", ""))
                    session["is_subscribed"] = subscribed
                    session["subscription_plan"] = plan or ""

                    if not subscribed:
                        flash("⚠ Your account has no active subscription. Some features may be limited.", "warning")

                    return redirect(url_for("todos"))
            elif status == 401 or status == 422:
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
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ─────────────────────────────────────────────────────────────
#  ROUTES — TODOS (PROTECTED)
# ─────────────────────────────────────────────────────────────

@app.route("/todos")
@login_required
def todos():
    return render_template("todos.html")



@app.route("/api/todos")
@login_required
def api_todos():
    status, data = laravel_get("apiTodos")
    if status == 200:
        items = data.get("data", [])
        if isinstance(items, dict):
            items = items.get("data", [])
        return jsonify({"ok": True, "todos": items})
    return jsonify({"ok": False, "message": data.get("message", "Failed to load todos")}), status


@app.route("/api/todos", methods=["POST"])
@login_required
def api_create_todo():
    payload = request.get_json()
    status, data = laravel_post("apiTodos", payload)
    if status in (200, 201):
        return jsonify({"ok": True, "todo": data.get("data", data)})
    return jsonify({"ok": False, "message": data.get("message", "Create failed")}), status


@app.route("/api/todos/<int:todo_id>/complete", methods=["PUT"])
@login_required
def api_complete_todo(todo_id):
    status, data = laravel_put(f"apiTodos/{todo_id}/complete", {})
    if status == 200:
        return jsonify({"ok": True, "todo": data.get("data", data)})
    return jsonify({"ok": False, "message": data.get("message", "Complete failed")}), status


@app.route("/api/todos/<int:todo_id>", methods=["DELETE"])
@login_required
def api_delete_todo(todo_id):
    status, _ = laravel_delete(f"apiTodos/{todo_id}")
    if status in (200, 204):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "message": "Delete failed"}), status


# ─────────────────────────────────────────────────────────────
#  ROUTES — ICAL
# ─────────────────────────────────────────────────────────────

@app.route("/api/alert")
@login_required
def api_alert():
    status, data = laravel_get("alert")
    if status == 200:
        return jsonify(data)
    return jsonify({"ok": False, "alert": None})


@app.route("/api/ical")
@login_required
def api_ical():
    status, data = laravel_get("ical")
    if status != 200:
        return jsonify({"ok": False, "message": data.get("message", "Failed to load iCal settings")}), status

    ical_url  = data.get("ical_url")
    ical_days = int(data.get("ical_days") or 7)

    if not ical_url:
        return jsonify({"ok": True, "events": [], "ical_days": ical_days})

    try:
        r = requests.get(ical_url, timeout=10)
        r.raise_for_status()
        cal = Calendar.from_ical(r.content)
    except Exception as e:
        return jsonify({"ok": False, "message": f"Failed to fetch iCal feed: {e}"})

    today    = date.today()
    cutoff   = today + timedelta(days=ical_days)
    events   = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dtstart = component.get("DTSTART")
        if not dtstart:
            continue

        val = dtstart.dt
        event_date = val.date() if isinstance(val, datetime) else val

        if not (today <= event_date <= cutoff):
            continue

        dtend = component.get("DTEND")
        end_val = dtend.dt if dtend else None
        end_date = (end_val.date() if isinstance(end_val, datetime) else end_val) if end_val else None

        events.append({
            "summary": str(component.get("SUMMARY", "No title")),
            "date":    event_date.isoformat(),
            "end":     end_date.isoformat() if end_date else None,
            "location": str(component.get("LOCATION", "")) or None,
        })

    events.sort(key=lambda e: e["date"])
    return jsonify({"ok": True, "events": events, "ical_days": ical_days})


# ─────────────────────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
