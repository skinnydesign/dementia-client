"""
Flask Todo Manager — Laravel API Client
All data is cached locally in SQLite and synced from Laravel in the background.
"""

import json
import os
import platform
import re
import subprocess
import time
from datetime import datetime

import requests
from flask import (Flask, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from functools import wraps

import db
import sync

# Locate templates/static — same level as app.py in Docker (via volume mounts),
# one level up on a bare Pi where the repo structure is app/ templates/ static/
_HERE = os.path.dirname(os.path.abspath(__file__))

def _find_dir(name: str) -> str:
    same_level = os.path.join(_HERE, name)
    if os.path.isdir(same_level):
        return same_level
    return os.path.join(os.path.dirname(_HERE), name)

app = Flask(__name__,
            template_folder=_find_dir('templates'),
            static_folder=_find_dir('static'))
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

@app.after_request
def no_cache(response):
    if "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


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

WLAN_IFACE = "wlan0"


def _use_nmcli() -> bool:
    """True when NetworkManager is active (Raspberry Pi OS Bookworm default)."""
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "--quiet", "NetworkManager"],
            timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def scan_wifi():
    OS = platform.system()
    networks = []
    try:
        if OS == "Linux":
            if _use_nmcli():
                # Trigger a fresh scan, then read results
                subprocess.run(["nmcli", "dev", "wifi", "rescan"],
                               capture_output=True, timeout=10)
                time.sleep(2)
                result = subprocess.run(
                    ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                     "dev", "wifi", "list"],
                    capture_output=True, text=True, timeout=10
                )
                seen = set()
                for line in result.stdout.strip().splitlines():
                    # terse mode: fields separated by ':'; literal colons escaped as '\:'
                    parts = re.split(r'(?<!\\):', line, maxsplit=3)
                    if len(parts) < 4:
                        continue
                    in_use   = parts[0].strip() == '*'
                    ssid     = parts[1].replace('\\:', ':').strip()
                    sig_str  = parts[2].strip()
                    security = parts[3].strip() or "Open"
                    if not ssid or ssid in seen:
                        continue
                    seen.add(ssid)
                    pct = int(sig_str) if sig_str.isdigit() else 0
                    networks.append({
                        "ssid":     ssid,
                        "signal":   pct,
                        "security": security,
                        "in_use":   in_use,
                        "bars":     max(1, min(4, pct // 25)),
                    })
            else:
                # Fallback: wpa_cli (older Pi OS / custom installs)
                cur = subprocess.run(
                    ["iwgetid", WLAN_IFACE, "--raw"],
                    capture_output=True, text=True, timeout=5
                )
                current_ssid = cur.stdout.strip()
                subprocess.run(
                    ["sudo", "wpa_cli", "-i", WLAN_IFACE, "scan"],
                    capture_output=True, timeout=5
                )
                time.sleep(2)
                result = subprocess.run(
                    ["sudo", "wpa_cli", "-i", WLAN_IFACE, "scan_results"],
                    capture_output=True, text=True, timeout=10
                )
                seen = set()
                for line in result.stdout.strip().splitlines():
                    if not line or line.startswith("Selected interface") or line.startswith("bssid"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 5:
                        continue
                    ssid = parts[4].strip()
                    if not ssid or ssid in seen:
                        continue
                    seen.add(ssid)
                    dbm = int(parts[2]) if parts[2].lstrip("-").isdigit() else -100
                    pct = max(0, min(100, 2 * (dbm + 100)))
                    flags = parts[3]
                    security = ("WPA2" if "WPA2" in flags else
                                "WPA"  if "WPA"  in flags else
                                "WEP"  if "WEP"  in flags else "Open")
                    networks.append({
                        "ssid":     ssid,
                        "signal":   pct,
                        "security": security,
                        "in_use":   ssid == current_ssid,
                        "bars":     max(1, min(4, pct // 25)),
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
                        "ssid":     parts[0],
                        "signal":   pct,
                        "security": parts[-1] if len(parts) > 5 else "Open",
                        "in_use":   False,
                        "bars":     max(1, min(4, pct // 25)),
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
            if _use_nmcli():
                # nmcli handles WPA handshake + DHCP + routing in one blocking call.
                # It returns only after the connection is fully up (or fails).
                cmd = ["nmcli", "dev", "wifi", "connect", ssid,
                       "ifname", WLAN_IFACE]
                if password:
                    cmd += ["password", password]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    return True, f"Connected to {ssid}"
                output = (r.stderr or r.stdout).strip()
                if any(k in output.lower() for k in ("secret", "password", "psk")):
                    return False, "Wrong password — authentication failed"
                return False, output or f"Could not connect to {ssid}"

            else:
                # Fallback: wpa_cli path for older Pi OS without NetworkManager
                r = subprocess.run(
                    ["sudo", "wpa_cli", "-i", WLAN_IFACE, "add_network"],
                    capture_output=True, text=True, timeout=10
                )
                net_id = r.stdout.strip().splitlines()[-1].strip()
                if not net_id.isdigit():
                    return False, f"Could not add network (wpa_cli: {net_id!r})"
                subprocess.run(
                    ["sudo", "wpa_cli", "-i", WLAN_IFACE, "set_network",
                     net_id, "ssid", f'"{ssid}"'],
                    capture_output=True, timeout=10
                )
                if password:
                    subprocess.run(
                        ["sudo", "wpa_cli", "-i", WLAN_IFACE, "set_network",
                         net_id, "psk", f'"{password}"'],
                        capture_output=True, timeout=10
                    )
                else:
                    subprocess.run(
                        ["sudo", "wpa_cli", "-i", WLAN_IFACE, "set_network",
                         net_id, "key_mgmt", "NONE"],
                        capture_output=True, timeout=10
                    )
                subprocess.run(["sudo", "wpa_cli", "-i", WLAN_IFACE,
                                 "select_network", net_id],
                               capture_output=True, timeout=10)
                subprocess.run(["sudo", "wpa_cli", "-i", WLAN_IFACE, "save_config"],
                               capture_output=True, timeout=10)

                wpa_done = False
                for _ in range(25):
                    time.sleep(1)
                    st = subprocess.run(
                        ["sudo", "wpa_cli", "-i", WLAN_IFACE, "status"],
                        capture_output=True, text=True, timeout=5
                    )
                    state = next(
                        (l.split("=", 1)[1].strip() for l in st.stdout.splitlines()
                         if l.startswith("wpa_state=")), ""
                    )
                    if state == "COMPLETED":
                        wpa_done = True
                        ip_out = subprocess.run(
                            ["ip", "-4", "addr", "show", WLAN_IFACE],
                            capture_output=True, text=True, timeout=5
                        )
                        if "inet " in ip_out.stdout:
                            return True, f"Connected to {ssid}"
                    elif not wpa_done:
                        nets = subprocess.run(
                            ["sudo", "wpa_cli", "-i", WLAN_IFACE, "list_networks"],
                            capture_output=True, text=True, timeout=5
                        )
                        for line in nets.stdout.splitlines():
                            parts = line.split("\t")
                            if (len(parts) >= 4 and parts[0] == net_id
                                    and "TEMP-DISABLED" in parts[3]):
                                return False, "Wrong password — authentication failed"

                if wpa_done:
                    return False, f"Connected to {ssid} but no IP — check your router"
                return False, f"Could not connect to {ssid} — check the password and try again"

        elif OS == "Darwin":
            r = subprocess.run(
                ["networksetup", "-setairportnetwork", "en0", ssid, password],
                capture_output=True, text=True, timeout=30
            )
            return r.returncode == 0, "Connected" if r.returncode == 0 else r.stderr.strip()

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


@app.route("/api/wifi/verify")
def wifi_verify():
    """Check if the API server is reachable. Polled by the frontend after WiFi connect."""
    base_url = load_config().get("api_base_url", "")
    if not base_url or "your-laravel-app" in base_url:
        return jsonify({"reachable": False, "message": "API URL not configured"})
    try:
        requests.get(base_url, timeout=5)
        return jsonify({"reachable": True})
    except requests.exceptions.ConnectionError:
        return jsonify({"reachable": False, "message": "Cannot reach the API server"})
    except Exception as e:
        return jsonify({"reachable": False, "message": str(e)})


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
        login    = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        if not login or not password:
            error = "Email or username and password are required."
        else:
            credential = {"email": login} if "@" in login else {"username": login}
            status, data = laravel_post("token", {**credential, "password": password})
            if status == 200:
                token = (data.get("token") or data.get("access_token") or
                         data.get("data", {}).get("token", ""))
                user  = data.get("user", data.get("data", {}).get("user", data))

                if not token:
                    error = "Login succeeded but no token was returned."
                else:
                    session["api_token"]  = token
                    session["user_name"]  = user.get("name", login)
                    session["user_email"] = user.get("email", login)

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


@app.route("/settings/wifi/scan")
@login_required
def settings_wifi_scan():
    return jsonify(scan_wifi())


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


@app.route("/api/system/update", methods=["POST"])
@login_required
def api_system_update():
    """Trigger a git pull + restart immediately (runs in background thread)."""
    import threading
    threading.Thread(target=sync._do_update, daemon=True).start()
    return jsonify({"ok": True, "message": "Update started."})


@app.route("/api/carer/status")
@login_required
def api_carer_status():
    visit   = db.get_active_carer_visit()
    names   = db.get_recent_carer_names()
    raw     = db.get_state("modules_enabled")
    modules = json.loads(raw) if raw else None
    # null from Laravel means all modules enabled
    carer_enabled = (modules is None) or ("carer" in modules)
    return jsonify({"ok": True, "active_visit": visit, "recent_names": names,
                    "carer_enabled": carer_enabled})


@app.route("/api/carer/arrive", methods=["POST"])
@login_required
def api_carer_arrive():
    data       = request.get_json()
    carer_name = (data.get("carer_name") or "").strip()
    if not carer_name:
        return jsonify({"ok": False, "message": "Carer name is required."}), 400

    arrived_at = datetime.now().isoformat(sep=" ", timespec="seconds")
    local_id   = db.create_carer_visit(carer_name, arrived_at)

    # Try to push to Laravel immediately; queue on failure
    try:
        status, resp = laravel_post("carer-visits", {
            "carer_name": carer_name,
            "arrived_at": arrived_at,
        })
        if status in (200, 201):
            laravel_id = (resp.get("data") or {}).get("id")
            if laravel_id:
                db.set_carer_visit_laravel_id(local_id, laravel_id)
        else:
            db.enqueue("carer_arrive", {"local_id": local_id,
                                         "carer_name": carer_name,
                                         "arrived_at": arrived_at})
    except Exception:
        db.enqueue("carer_arrive", {"local_id": local_id,
                                     "carer_name": carer_name,
                                     "arrived_at": arrived_at})

    return jsonify({"ok": True, "local_id": local_id,
                    "carer_name": carer_name, "arrived_at": arrived_at})


@app.route("/api/carer/leave", methods=["POST"])
@login_required
def api_carer_leave():
    visit = db.get_active_carer_visit()
    if not visit:
        return jsonify({"ok": False, "message": "No active visit found."}), 404

    left_at = datetime.now().isoformat(sep=" ", timespec="seconds")
    db.close_carer_visit(visit["id"], left_at)

    if visit.get("laravel_id"):
        try:
            laravel_put(f"carer-visits/{visit['laravel_id']}/leave",
                        {"left_at": left_at})
        except Exception:
            db.enqueue("carer_leave", {"local_id": visit["id"],
                                        "laravel_id": visit["laravel_id"],
                                        "left_at": left_at})
    else:
        db.enqueue("carer_leave", {"local_id": visit["id"],
                                    "laravel_id": None,
                                    "left_at": left_at})

    return jsonify({"ok": True, "left_at": left_at})


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
    suspended = db.get_state("schedules_suspended") == "1"
    if suspended:
        return jsonify({"ok": True, "suspended": True, "items": []})
    items = db.get_due_items()
    return jsonify({
        "ok":        True,
        "suspended": False,
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


@app.route("/api/layout")
@login_required
def api_layout():
    return jsonify({"ok": True, "layout": db.get_layout()})


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
