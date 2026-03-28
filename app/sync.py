"""
Background sync — pulls data from Laravel into SQLite every 5 minutes.
iCal feed is re-fetched every 30 minutes.
Pending writes (completions) are pushed to Laravel when online.
"""

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

import requests
from icalendar import Calendar

import db

log = logging.getLogger(__name__)

SYNC_INTERVAL = 300    # 5 minutes — main data
ICAL_INTERVAL = 1800   # 30 minutes — external iCal fetch


# ─────────────────────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────────────────────

def start() -> None:
    """Start the background sync thread (call once at app startup)."""
    t = threading.Thread(target=_loop, daemon=True, name="sync")
    t.start()
    log.info("Background sync started.")


def trigger() -> None:
    """Run a sync immediately in a one-shot thread (e.g. after login)."""
    threading.Thread(target=_run, daemon=True, name="sync-now").start()


# ─────────────────────────────────────────────────────────────
#  LOOP
# ─────────────────────────────────────────────────────────────

def _loop() -> None:
    while True:
        time.sleep(SYNC_INTERVAL)
        _run()


def _run() -> None:
    token    = db.get_state("api_token")
    base_url = db.get_state("api_base_url")
    if not token or not base_url:
        return

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    base = base_url.rstrip("/")

    try:
        _push_queue(base, headers)
        _pull_schedule(base, headers)
        _pull_todos(base, headers)
        _pull_alert(base, headers)
        _pull_layout(base, headers)
        _maybe_pull_ical(base, headers)
        db.set_state("last_sync", datetime.now().isoformat())
        log.info("Sync complete.")
    except Exception as e:
        log.warning(f"Sync failed: {e}")


# ─────────────────────────────────────────────────────────────
#  PUSH QUEUE
# ─────────────────────────────────────────────────────────────

def _push_queue(base: str, headers: dict) -> None:
    for item in db.get_queue():
        payload = json.loads(item["payload"])
        action  = item["action"]
        ok      = False

        try:
            if action == "complete_todo":
                r = requests.put(
                    f"{base}/apiTodos/{payload['id']}/complete",
                    json={}, headers=headers, timeout=10
                )
                ok = r.status_code == 200

            elif action == "complete_schedule":
                r = requests.put(
                    f"{base}/schedule/{payload['id']}/complete",
                    json={}, headers=headers, timeout=10
                )
                ok = r.status_code == 200

        except Exception as e:
            log.warning(f"Queue push failed ({action}): {e}")

        if ok:
            db.dequeue(item["id"])


# ─────────────────────────────────────────────────────────────
#  PULL HELPERS
# ─────────────────────────────────────────────────────────────

def _pull_schedule(base: str, headers: dict) -> None:
    try:
        r = requests.get(f"{base}/schedule", headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            db.upsert_schedule(data.get("items", []))
    except Exception as e:
        log.warning(f"Schedule sync failed: {e}")


def _pull_todos(base: str, headers: dict) -> None:
    try:
        r = requests.get(f"{base}/apiTodos", headers=headers, timeout=10)
        if r.status_code == 200:
            data  = r.json()
            items = data.get("data", [])
            if isinstance(items, dict):
                items = items.get("data", [])
            db.upsert_todos(items)
    except Exception as e:
        log.warning(f"Todos sync failed: {e}")


def _pull_alert(base: str, headers: dict) -> None:
    try:
        r = requests.get(f"{base}/alert", headers=headers, timeout=10)
        if r.status_code == 200:
            data  = r.json()
            alert = data.get("alert")
            if alert:
                db.set_alert(alert.get("message"), alert.get("expires_at"))
            else:
                db.set_alert(None, None)
    except Exception as e:
        log.warning(f"Alert sync failed: {e}")


def _pull_layout(base: str, headers: dict) -> None:
    try:
        r = requests.get(f"{base}/layout", headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            db.set_layout(data.get("layout") or {})
    except Exception as e:
        log.warning(f"Layout sync failed: {e}")


def _maybe_pull_ical(base: str, headers: dict) -> None:
    last = db.get_state("last_ical_sync")
    if last:
        age = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
        if age < ICAL_INTERVAL:
            return
    _pull_ical(base, headers)


def _pull_ical(base: str, headers: dict) -> None:
    try:
        # Get iCal settings from Laravel
        r = requests.get(f"{base}/ical", headers=headers, timeout=10)
        if r.status_code != 200:
            return

        data      = r.json()
        ical_url  = data.get("ical_url")
        ical_days = int(data.get("ical_days") or 7)

        db.set_state("ical_url",  ical_url or "")
        db.set_state("ical_days", str(ical_days))

        if not ical_url:
            db.replace_ical_events([])
            db.set_state("last_ical_sync", datetime.now().isoformat())
            return

        # Fetch the actual iCal feed
        feed = requests.get(ical_url, timeout=15)
        feed.raise_for_status()
        cal = Calendar.from_ical(feed.content)

        today  = date.today()
        cutoff = today + timedelta(days=ical_days)
        events = []

        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            dtstart = component.get("DTSTART")
            if not dtstart:
                continue

            val        = dtstart.dt
            has_time   = isinstance(val, datetime)
            event_date = val.date() if has_time else val

            if not (today <= event_date <= cutoff):
                continue

            if has_time and val.tzinfo is not None:
                val = val.astimezone().replace(tzinfo=None)

            dtend        = component.get("DTEND")
            end_val      = dtend.dt if dtend else None
            end_has_time = isinstance(end_val, datetime)
            end_date     = (end_val.date() if end_has_time else end_val) if end_val else None

            if end_has_time and end_val.tzinfo is not None:
                end_val = end_val.astimezone().replace(tzinfo=None)

            events.append({
                "summary":  str(component.get("SUMMARY", "No title")),
                "date":     event_date.isoformat(),
                "end":      end_date.isoformat() if end_date else None,
                "time":     val.strftime("%H:%M") if has_time else None,
                "end_time": end_val.strftime("%H:%M") if end_has_time else None,
                "location": str(component.get("LOCATION", "")) or None,
            })

        events.sort(key=lambda e: e["date"])
        db.replace_ical_events(events)
        db.set_state("last_ical_sync", datetime.now().isoformat())
        log.info(f"iCal synced: {len(events)} events.")

    except Exception as e:
        log.warning(f"iCal sync failed: {e}")
