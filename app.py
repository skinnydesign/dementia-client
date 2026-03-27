"""
Flask Todo Manager — Laravel API Client
"""

import json
import os
import platform
import subprocess
import threading

import requests
from flask import (Flask, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-please")

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".flask_todo_config.json")

# ─────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "api_base_url": "https://your-laravel-app.com/api",
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


def laravel_get(path):
    try:
        r = requests.get(api_url(path), headers=api_headers(), timeout=10)
        return r.status_code, r.json()
    except requests.exceptions.ConnectionError:
        return 503, {"message": "Cannot reach the API server."}
    except Exception as e:
        return 500, {"message": str(e)}


def laravel_post(path, payload):
    try:
        r = requests.post(api_url(path), json=payload, headers=api_headers(), timeout=10)
        return r.status_code, r.json()
    except requests.exceptions.ConnectionError:
        return 503, {"message": "Cannot reach the API server."}
    except Exception as e:
        return 500, {"message": str(e)}


def laravel_put(path, payload):
    try:
        r = requests.put(api_url(path), json=payload, headers=api_headers(), timeout=10)
        return r.status_code, r.json()
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
    return render_template("settings.html", config=cfg)


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
#  ROUTES — AUTH
# ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    if session.get("api_token"):
        return redirect(url_for("todos"))
    return redirect(url_for("login"))


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
            status, data = laravel_post("login", {"email": email, "password": password})
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


@app.route("/logout")
def logout():
    token = session.get("api_token")
    if token:
        try:
            requests.post(api_url("logout"), headers=api_headers(), timeout=5)
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
    status, data = laravel_get("todos")
    if status == 200:
        items = data if isinstance(data, list) else data.get("data", data.get("todos", []))
        return jsonify({"ok": True, "todos": items})
    return jsonify({"ok": False, "message": data.get("message", "Failed to load todos")}), status


@app.route("/api/todos", methods=["POST"])
@login_required
def api_create_todo():
    payload = request.get_json()
    status, data = laravel_post("todos", payload)
    if status in (200, 201):
        return jsonify({"ok": True, "todo": data.get("data", data)})
    return jsonify({"ok": False, "message": data.get("message", "Create failed")}), status


@app.route("/api/todos/<int:todo_id>", methods=["PUT"])
@login_required
def api_update_todo(todo_id):
    payload = request.get_json()
    status, data = laravel_put(f"todos/{todo_id}", payload)
    if status == 200:
        return jsonify({"ok": True, "todo": data.get("data", data)})
    return jsonify({"ok": False, "message": data.get("message", "Update failed")}), status


@app.route("/api/todos/<int:todo_id>", methods=["DELETE"])
@login_required
def api_delete_todo(todo_id):
    status, _ = laravel_delete(f"todos/{todo_id}")
    if status in (200, 204):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "message": "Delete failed"}), status


# ─────────────────────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
