"""
Tests for db.py — all SQLite operations.
"""
import json
from datetime import datetime, timedelta

import pytest
import db


# ─────────────────────────────────────────────────────────────
#  init_db
# ─────────────────────────────────────────────────────────────

def test_init_db_creates_all_tables():
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    expected = {
        "todos", "schedule_items", "schedule_completions",
        "ical_events", "alert_cache", "layout_cache",
        "sync_queue", "sync_state", "carer_visits",
    }
    assert expected.issubset(tables)


# ─────────────────────────────────────────────────────────────
#  sync_state
# ─────────────────────────────────────────────────────────────

def test_set_and_get_state():
    db.set_state("test_key", "hello")
    assert db.get_state("test_key") == "hello"


def test_get_state_missing_key_returns_none():
    assert db.get_state("no_such_key") is None


def test_set_state_overwrites_existing():
    db.set_state("k", "first")
    db.set_state("k", "second")
    assert db.get_state("k") == "second"


def test_set_state_none_clears_value():
    db.set_state("k", "something")
    db.set_state("k", None)
    assert db.get_state("k") is None


# ─────────────────────────────────────────────────────────────
#  todos
# ─────────────────────────────────────────────────────────────

def test_upsert_and_get_todos():
    db.upsert_todos([
        {"id": 1, "todo": "Buy milk", "completed": False, "completed_at": None},
        {"id": 2, "todo": "Call doctor", "completed": True, "completed_at": "2026-01-01"},
    ])
    todos = db.get_todos()
    assert len(todos) == 2
    assert todos[0]["todo"] == "Buy milk"
    assert todos[0]["completed"] == 0
    assert todos[1]["completed"] == 1


def test_upsert_todos_replaces_all():
    db.upsert_todos([{"id": 1, "todo": "Old", "completed": False, "completed_at": None}])
    db.upsert_todos([{"id": 2, "todo": "New", "completed": False, "completed_at": None}])
    todos = db.get_todos()
    assert len(todos) == 1
    assert todos[0]["todo"] == "New"


def test_complete_todo_locally():
    db.upsert_todos([{"id": 5, "todo": "Test task", "completed": False, "completed_at": None}])
    db.complete_todo_locally(5)
    todos = db.get_todos()
    assert todos[0]["completed"] == 1
    assert todos[0]["completed_at"] is not None


def test_get_todos_empty():
    assert db.get_todos() == []


# ─────────────────────────────────────────────────────────────
#  schedule
# ─────────────────────────────────────────────────────────────

SCHEDULE_ITEM = {
    "id": 1,
    "name": "Morning meds",
    "frequency": "daily",
    "day_of_week": None,
    "scheduled_time": "08:00",
    "last_completed_at": None,
    "is_active": True,
}


def test_upsert_and_get_schedule_items():
    db.upsert_schedule([SCHEDULE_ITEM])
    items = db.get_schedule_items()
    assert len(items) == 1
    assert items[0]["name"] == "Morning meds"


def test_upsert_schedule_replaces_all():
    db.upsert_schedule([SCHEDULE_ITEM])
    db.upsert_schedule([{**SCHEDULE_ITEM, "id": 2, "name": "Evening meds"}])
    items = db.get_schedule_items()
    assert len(items) == 1
    assert items[0]["name"] == "Evening meds"


def test_inactive_items_excluded_from_get():
    db.upsert_schedule([{**SCHEDULE_ITEM, "is_active": False}])
    assert db.get_schedule_items() == []


def test_complete_schedule_locally_updates_timestamp():
    db.upsert_schedule([SCHEDULE_ITEM])
    db.complete_schedule_locally(1)
    items = db.get_schedule_items()
    assert items[0]["last_completed_at"] is not None


def test_complete_schedule_locally_inserts_completion_record():
    db.upsert_schedule([SCHEDULE_ITEM])
    db.complete_schedule_locally(1)
    completions = db.get_completions(1)
    assert len(completions) == 1


def test_upsert_completions():
    db.upsert_schedule([SCHEDULE_ITEM])
    db.upsert_completions(1, [
        {"id": 10, "completed_at": "2026-04-01 08:05:00"},
        {"id": 11, "completed_at": "2026-04-02 08:10:00"},
    ])
    completions = db.get_completions(1)
    assert len(completions) == 2


# ─────────────────────────────────────────────────────────────
#  is_due — daily
# ─────────────────────────────────────────────────────────────

def _item(frequency="daily", scheduled_time="08:00", last_completed_at=None, day_of_week=None):
    return {
        "id": 1, "name": "Test", "frequency": frequency,
        "scheduled_time": scheduled_time, "last_completed_at": last_completed_at,
        "day_of_week": day_of_week, "is_active": 1,
    }


def test_daily_due_after_time_never_completed():
    now = datetime(2026, 4, 6, 9, 0)   # 09:00, scheduled 08:00
    assert db.is_due(_item("daily", "08:00"), now) is True


def test_daily_not_due_before_time():
    now = datetime(2026, 4, 6, 7, 0)   # 07:00, scheduled 08:00
    assert db.is_due(_item("daily", "08:00"), now) is False


def test_daily_not_due_if_completed_today():
    now = datetime(2026, 4, 6, 10, 0)
    last = "2026-04-06 08:05:00"
    assert db.is_due(_item("daily", "08:00", last), now) is False


def test_daily_due_if_completed_yesterday():
    now = datetime(2026, 4, 6, 10, 0)
    last = "2026-04-05 08:05:00"
    assert db.is_due(_item("daily", "08:00", last), now) is True


# ─────────────────────────────────────────────────────────────
#  is_due — every_other_day
# ─────────────────────────────────────────────────────────────

def test_every_other_day_due_never_completed():
    now = datetime(2026, 4, 6, 10, 0)
    assert db.is_due(_item("every_other_day", "08:00"), now) is True


def test_every_other_day_not_due_completed_today():
    now = datetime(2026, 4, 6, 10, 0)
    last = "2026-04-06 08:05:00"
    assert db.is_due(_item("every_other_day", "08:00", last), now) is False


def test_every_other_day_due_after_two_days():
    now = datetime(2026, 4, 6, 10, 0)
    last = "2026-04-04 08:05:00"   # 2 days ago
    assert db.is_due(_item("every_other_day", "08:00", last), now) is True


def test_every_other_day_not_due_after_one_day():
    now = datetime(2026, 4, 6, 10, 0)
    last = "2026-04-05 08:05:00"   # only 1 day ago
    assert db.is_due(_item("every_other_day", "08:00", last), now) is False


# ─────────────────────────────────────────────────────────────
#  is_due — weekly
# ─────────────────────────────────────────────────────────────

def test_weekly_due_on_correct_day_after_time():
    # 2026-04-06 is a Monday
    now = datetime(2026, 4, 6, 10, 0)
    assert db.is_due(_item("weekly", "08:00", day_of_week="monday"), now) is True


def test_weekly_not_due_on_wrong_day():
    # 2026-04-06 is a Monday, item scheduled Tuesday
    now = datetime(2026, 4, 6, 10, 0)
    assert db.is_due(_item("weekly", "08:00", day_of_week="tuesday"), now) is False


def test_weekly_not_due_before_time_on_correct_day():
    now = datetime(2026, 4, 6, 7, 0)   # Monday, before 08:00
    assert db.is_due(_item("weekly", "08:00", day_of_week="monday"), now) is False


def test_weekly_not_due_if_completed_today():
    now = datetime(2026, 4, 6, 10, 0)
    last = "2026-04-06 08:05:00"
    assert db.is_due(_item("weekly", "08:00", last, "monday"), now) is False


# ─────────────────────────────────────────────────────────────
#  iCal events
# ─────────────────────────────────────────────────────────────

def test_replace_and_get_ical_events():
    db.replace_ical_events([
        {"summary": "Doctor appt", "date": "2026-04-10", "end": None,
         "time": "14:30", "end_time": None, "location": "Surgery"},
        {"summary": "Birthday", "date": "2026-04-15", "end": None,
         "time": None, "end_time": None, "location": None},
    ])
    events = db.get_ical_events()
    assert len(events) == 2
    assert events[0]["summary"] == "Doctor appt"
    assert events[0]["time"] == "14:30"


def test_replace_ical_events_clears_old():
    db.replace_ical_events([{"summary": "Old", "date": "2026-01-01",
                              "end": None, "time": None, "end_time": None, "location": None}])
    db.replace_ical_events([])
    assert db.get_ical_events() == []


# ─────────────────────────────────────────────────────────────
#  alert
# ─────────────────────────────────────────────────────────────

def test_set_and_get_active_alert():
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    db.set_alert("Take medication", future)
    alert = db.get_alert()
    assert alert is not None
    assert alert["message"] == "Take medication"
    assert alert["seconds_remaining"] > 0


def test_get_alert_returns_none_when_expired():
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    db.set_alert("Old alert", past)
    assert db.get_alert() is None


def test_get_alert_returns_none_when_empty():
    assert db.get_alert() is None


def test_clear_alert():
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    db.set_alert("Alert", future)
    db.set_alert(None, None)
    assert db.get_alert() is None


# ─────────────────────────────────────────────────────────────
#  layout
# ─────────────────────────────────────────────────────────────

def test_set_and_get_layout():
    db.set_layout({"show_todos": True, "show_calendar": False})
    layout = db.get_layout()
    assert layout["show_todos"] is True
    assert layout["show_calendar"] is False


def test_get_layout_returns_empty_dict_when_unset():
    assert db.get_layout() == {}


# ─────────────────────────────────────────────────────────────
#  carer visits
# ─────────────────────────────────────────────────────────────

def test_create_and_get_active_carer_visit():
    local_id = db.create_carer_visit("Jane", "2026-04-06 10:00:00")
    visit = db.get_active_carer_visit()
    assert visit is not None
    assert visit["carer_name"] == "Jane"
    assert visit["left_at"] is None


def test_close_carer_visit():
    local_id = db.create_carer_visit("Jane", "2026-04-06 10:00:00")
    db.close_carer_visit(local_id, "2026-04-06 12:00:00")
    assert db.get_active_carer_visit() is None


def test_set_carer_visit_laravel_id():
    local_id = db.create_carer_visit("Jane", "2026-04-06 10:00:00")
    db.set_carer_visit_laravel_id(local_id, 99)
    visit = db.get_active_carer_visit()
    assert visit["laravel_id"] == 99


def test_get_recent_carer_names():
    db.create_carer_visit("Alice", "2026-04-01 10:00:00")
    db.create_carer_visit("Bob", "2026-04-02 10:00:00")
    db.create_carer_visit("Alice", "2026-04-03 10:00:00")  # Alice again
    names = db.get_recent_carer_names()
    assert "Alice" in names
    assert "Bob" in names
    assert len(names) == 2  # deduplicated


def test_no_active_visit_when_none():
    assert db.get_active_carer_visit() is None


# ─────────────────────────────────────────────────────────────
#  sync queue
# ─────────────────────────────────────────────────────────────

def test_enqueue_and_get_queue():
    db.enqueue("complete_todo", {"id": 7})
    queue = db.get_queue()
    assert len(queue) == 1
    assert queue[0]["action"] == "complete_todo"
    assert json.loads(queue[0]["payload"]) == {"id": 7}


def test_dequeue_removes_item():
    db.enqueue("complete_todo", {"id": 7})
    item_id = db.get_queue()[0]["id"]
    db.dequeue(item_id)
    assert db.get_queue() == []


def test_dequeue_by_action():
    db.enqueue("complete_todo", {"id": 5})
    db.enqueue("complete_todo", {"id": 6})
    db.dequeue_by_action("complete_todo", 5)
    queue = db.get_queue()
    assert len(queue) == 1
    assert json.loads(queue[0]["payload"])["id"] == 6


def test_queue_preserves_order():
    for i in range(3):
        db.enqueue("complete_todo", {"id": i})
    ids = [json.loads(q["payload"])["id"] for q in db.get_queue()]
    assert ids == [0, 1, 2]
