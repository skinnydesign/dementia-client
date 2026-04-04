"""
Local SQLite cache — all reads come from here, synced from Laravel in the background.
"""

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DB_PATH = os.path.join(
    os.environ.get("DATA_DIR", os.path.expanduser("~")), "control.db"
)


# ─────────────────────────────────────────────────────────────
#  CONNECTION
# ─────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─────────────────────────────────────────────────────────────
#  INIT
# ─────────────────────────────────────────────────────────────

def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS todos (
                id          INTEGER PRIMARY KEY,
                todo        TEXT    NOT NULL,
                completed   INTEGER DEFAULT 0,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS schedule_items (
                id                INTEGER PRIMARY KEY,
                name              TEXT NOT NULL,
                frequency         TEXT NOT NULL,
                day_of_week       TEXT,
                scheduled_time    TEXT NOT NULL,
                last_completed_at TEXT,
                is_active         INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS ical_events (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                summary  TEXT NOT NULL,
                date     TEXT NOT NULL,
                end_date TEXT,
                time     TEXT,
                end_time TEXT,
                location TEXT
            );

            CREATE TABLE IF NOT EXISTS alert_cache (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                message    TEXT,
                expires_at TEXT
            );

            CREATE TABLE IF NOT EXISTS layout_cache (
                id   INTEGER PRIMARY KEY CHECK (id = 1),
                data TEXT
            );

            CREATE TABLE IF NOT EXISTS schedule_completions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                laravel_id   INTEGER,
                schedule_id  INTEGER NOT NULL,
                completed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_completions_schedule
                ON schedule_completions (schedule_id, completed_at DESC);

            CREATE TABLE IF NOT EXISTS carer_visits (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                laravel_id   INTEGER,
                carer_name   TEXT NOT NULL,
                arrived_at   TEXT NOT NULL,
                left_at      TEXT
            );

            CREATE TABLE IF NOT EXISTS sync_queue (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                action     TEXT NOT NULL,
                payload    TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sync_state (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)


# ─────────────────────────────────────────────────────────────
#  SYNC STATE (key-value store)
# ─────────────────────────────────────────────────────────────

def get_state(key: str) -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_state(key: str, value: str | None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sync_state (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, value)
        )


# ─────────────────────────────────────────────────────────────
#  TODOS
# ─────────────────────────────────────────────────────────────

def get_todos() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM todos ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_todos(items: list[dict]) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM todos")
        conn.executemany(
            "INSERT INTO todos (id, todo, completed, completed_at) VALUES (?, ?, ?, ?)",
            [(i["id"], i["todo"], int(i.get("completed", False)), i.get("completed_at")) for i in items]
        )


def complete_todo_locally(todo_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE todos SET completed = 1, completed_at = datetime('now') WHERE id = ?",
            (todo_id,)
        )


# ─────────────────────────────────────────────────────────────
#  SCHEDULE
# ─────────────────────────────────────────────────────────────

def get_schedule_items() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule_items WHERE is_active = 1 ORDER BY scheduled_time"
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_schedule(items: list[dict]) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM schedule_items")
        conn.executemany(
            """INSERT INTO schedule_items
               (id, name, frequency, day_of_week, scheduled_time, last_completed_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(i["id"], i["name"], i["frequency"], i.get("day_of_week"),
              i["scheduled_time"][:5], i.get("last_completed_at"), int(i.get("is_active", True)))
             for i in items]
        )


def complete_schedule_locally(item_id: int) -> None:
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with get_db() as conn:
        conn.execute(
            "UPDATE schedule_items SET last_completed_at = ? WHERE id = ?",
            (now, item_id)
        )
        conn.execute(
            "INSERT INTO schedule_completions (schedule_id, completed_at) VALUES (?, ?)",
            (item_id, now)
        )


def get_completions(schedule_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule_completions WHERE schedule_id = ? ORDER BY completed_at DESC LIMIT 20",
            (schedule_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_completions(schedule_id: int, completions: list[dict]) -> None:
    """Replace completions for a schedule item with data from Laravel."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM schedule_completions WHERE schedule_id = ? AND laravel_id IS NOT NULL",
            (schedule_id,)
        )
        conn.executemany(
            "INSERT OR IGNORE INTO schedule_completions (laravel_id, schedule_id, completed_at) VALUES (?, ?, ?)",
            [(c["id"], schedule_id, c["completed_at"]) for c in completions]
        )


def is_due(item: dict, now: datetime = None) -> bool:
    """Replicates the Laravel isDue() logic locally."""
    try:
        if now is None:
            now = _local_now()
        t       = datetime.strptime(item["scheduled_time"][:5], "%H:%M").time()
        today_s = datetime.combine(now.date(), t)
        last    = (datetime.fromisoformat(item["last_completed_at"])
                   if item.get("last_completed_at") else None)
        if last is not None and last.tzinfo is not None:
            tz = ZoneInfo(get_state("app_timezone") or "UTC")
            last = last.astimezone(tz).replace(tzinfo=None)
        freq    = item["frequency"]

        if freq == "daily":
            if now < today_s:
                return False
            return (not last) or last < today_s

        if freq == "every_other_day":
            if not last:
                return True
            next_due = (last + timedelta(days=2)).replace(
                hour=t.hour, minute=t.minute, second=0, microsecond=0)
            return now >= next_due

        if freq == "weekly":
            day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                       "friday": 4, "saturday": 5, "sunday": 6}
            target = day_map.get((item.get("day_of_week") or "").lower(), 0)
            if date.today().weekday() != target:
                return False
            if now < today_s:
                return False
            return (not last) or last < today_s

    except Exception:
        pass
    return False


def _local_now() -> datetime:
    """Return naive datetime representing current time in the user's configured timezone."""
    tz_name = get_state("app_timezone") or "UTC"
    try:
        return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
    except ZoneInfoNotFoundError:
        return datetime.now()


def get_due_items() -> list[dict]:
    now = _local_now()
    items = get_schedule_items()
    return [i for i in items if is_due(i, now)]


# ─────────────────────────────────────────────────────────────
#  ICAL EVENTS
# ─────────────────────────────────────────────────────────────

def get_ical_events() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ical_events ORDER BY date"
        ).fetchall()
        return [dict(r) for r in rows]


def replace_ical_events(events: list[dict]) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM ical_events")
        conn.executemany(
            """INSERT INTO ical_events (summary, date, end_date, time, end_time, location)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(e["summary"], e["date"], e.get("end"), e.get("time"),
              e.get("end_time"), e.get("location")) for e in events]
        )


# ─────────────────────────────────────────────────────────────
#  ALERT
# ─────────────────────────────────────────────────────────────

def get_alert() -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM alert_cache WHERE id = 1").fetchone()
        if not row or not row["message"] or not row["expires_at"]:
            return None
        try:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires.tzinfo is not None:
                tz = ZoneInfo(get_state("app_timezone") or "UTC")
                expires = expires.astimezone(tz).replace(tzinfo=None)
            now = _local_now()
            if expires <= now:
                return None
            seconds_remaining = int((expires - now).total_seconds())
            return {"message": row["message"], "expires_at": row["expires_at"],
                    "seconds_remaining": seconds_remaining}
        except Exception:
            return None


def set_alert(message: str | None, expires_at: str | None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO alert_cache (id, message, expires_at) VALUES (1, ?, ?)",
            (message, expires_at)
        )


# ─────────────────────────────────────────────────────────────
#  LAYOUT
# ─────────────────────────────────────────────────────────────

def get_layout() -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT data FROM layout_cache WHERE id = 1").fetchone()
        if not row or not row["data"]:
            return {}
        try:
            return json.loads(row["data"])
        except Exception:
            return {}


def set_layout(data: dict) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO layout_cache (id, data) VALUES (1, ?)",
            (json.dumps(data),)
        )


# ─────────────────────────────────────────────────────────────
#  CARER VISITS
# ─────────────────────────────────────────────────────────────

def get_active_carer_visit() -> dict | None:
    """Return the open visit (no left_at), or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM carer_visits WHERE left_at IS NULL ORDER BY arrived_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def create_carer_visit(carer_name: str, arrived_at: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO carer_visits (carer_name, arrived_at) VALUES (?, ?)",
            (carer_name, arrived_at)
        )
        return cur.lastrowid


def close_carer_visit(local_id: int, left_at: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE carer_visits SET left_at = ? WHERE id = ?",
            (left_at, local_id)
        )


def set_carer_visit_laravel_id(local_id: int, laravel_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE carer_visits SET laravel_id = ? WHERE id = ?",
            (laravel_id, local_id)
        )


def get_recent_carer_names(limit: int = 6) -> list[str]:
    """Return distinct carer names from most recent visits."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT carer_name FROM carer_visits
               GROUP BY carer_name
               ORDER BY MAX(arrived_at) DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()
        return [r["carer_name"] for r in rows]


# ─────────────────────────────────────────────────────────────
#  SYNC QUEUE
# ─────────────────────────────────────────────────────────────

def enqueue(action: str, payload: dict) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sync_queue (action, payload) VALUES (?, ?)",
            (action, json.dumps(payload))
        )


def get_queue() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_queue ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def dequeue(item_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM sync_queue WHERE id = ?", (item_id,))


def dequeue_by_action(action: str, payload_id: int) -> None:
    """Remove a queued item by action name and the id inside its payload."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, payload FROM sync_queue WHERE action = ?", (action,)
        ).fetchall()
        for row in rows:
            try:
                if json.loads(row["payload"]).get("id") == payload_id:
                    conn.execute("DELETE FROM sync_queue WHERE id = ?", (row["id"],))
            except Exception:
                pass
