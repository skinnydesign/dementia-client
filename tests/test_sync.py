"""
Tests for sync.py — background pull/push logic.
All HTTP calls are mocked; no real network needed.
"""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

import pytest
import db
from sync import (
    _pull_todos,
    _pull_schedule,
    _pull_alert,
    _pull_layout,
    _push_queue,
    _run,
)


BASE    = "http://test-laravel/api"
HEADERS = {"Authorization": "Bearer test-token", "Accept": "application/json",
           "Content-Type": "application/json"}


def _mock_get(payload, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload
    return m


def _mock_put(status=200):
    m = MagicMock()
    m.status_code = status
    return m


# ─────────────────────────────────────────────────────────────
#  _pull_todos
# ─────────────────────────────────────────────────────────────

def test_pull_todos_saves_to_db():
    payload = {"data": {"data": [
        {"id": 1, "todo": "Feed dog", "completed": False, "completed_at": None},
        {"id": 2, "todo": "Walk", "completed": True, "completed_at": "2026-04-05"},
    ]}}
    with patch("requests.get", return_value=_mock_get(payload)):
        _pull_todos(BASE, HEADERS)
    todos = db.get_todos()
    assert len(todos) == 2
    assert todos[0]["todo"] == "Feed dog"


def test_pull_todos_handles_flat_data_key():
    """Laravel sometimes returns data.data as a list directly."""
    payload = {"data": [
        {"id": 3, "todo": "Water plants", "completed": False, "completed_at": None},
    ]}
    with patch("requests.get", return_value=_mock_get(payload)):
        _pull_todos(BASE, HEADERS)
    todos = db.get_todos()
    assert len(todos) == 1
    assert todos[0]["todo"] == "Water plants"


def test_pull_todos_does_nothing_on_non_200():
    db.upsert_todos([{"id": 1, "todo": "Existing", "completed": False, "completed_at": None}])
    with patch("requests.get", return_value=_mock_get({}, status=401)):
        _pull_todos(BASE, HEADERS)
    # Existing data should be untouched
    assert len(db.get_todos()) == 1


def test_pull_todos_handles_network_error():
    import requests as req
    with patch("requests.get", side_effect=req.exceptions.ConnectionError):
        _pull_todos(BASE, HEADERS)  # should not raise
    assert db.get_todos() == []


# ─────────────────────────────────────────────────────────────
#  _pull_schedule
# ─────────────────────────────────────────────────────────────

def test_pull_schedule_saves_items():
    payload = {"items": [{
        "id": 1, "name": "Morning meds", "frequency": "daily",
        "day_of_week": None, "scheduled_time": "08:00",
        "last_completed_at": None, "is_active": True,
        "completions": [],
    }]}
    with patch("requests.get", return_value=_mock_get(payload)):
        _pull_schedule(BASE, HEADERS)
    items = db.get_schedule_items()
    assert len(items) == 1
    assert items[0]["name"] == "Morning meds"


def test_pull_schedule_saves_completions():
    payload = {"items": [{
        "id": 2, "name": "Vitamins", "frequency": "daily",
        "day_of_week": None, "scheduled_time": "09:00",
        "last_completed_at": "2026-04-05 09:01:00", "is_active": True,
        "completions": [
            {"id": 10, "completed_at": "2026-04-05 09:01:00"},
            {"id": 11, "completed_at": "2026-04-04 09:02:00"},
        ],
    }]}
    with patch("requests.get", return_value=_mock_get(payload)):
        _pull_schedule(BASE, HEADERS)
    completions = db.get_completions(2)
    assert len(completions) == 2


# ─────────────────────────────────────────────────────────────
#  _pull_alert
# ─────────────────────────────────────────────────────────────

def test_pull_alert_stores_active_alert():
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    payload = {"alert": {"message": "Doctor at 3pm", "expires_at": future}}
    with patch("requests.get", return_value=_mock_get(payload)):
        _pull_alert(BASE, HEADERS)
    alert = db.get_alert()
    assert alert is not None
    assert alert["message"] == "Doctor at 3pm"


def test_pull_alert_clears_when_no_alert():
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    db.set_alert("Old alert", future)
    with patch("requests.get", return_value=_mock_get({"alert": None})):
        _pull_alert(BASE, HEADERS)
    assert db.get_alert() is None


# ─────────────────────────────────────────────────────────────
#  _pull_layout
# ─────────────────────────────────────────────────────────────

def test_pull_layout_stores_layout():
    payload = {
        "layout": {"show_clock": True, "show_todos": True},
        "modules_enabled": ["todos", "calendar", "carer"],
        "timezone": "Europe/London",
    }
    with patch("requests.get", return_value=_mock_get(payload)):
        _pull_layout(BASE, HEADERS)
    layout = db.get_layout()
    assert layout["show_clock"] is True
    assert db.get_state("app_timezone") == "Europe/London"
    modules = json.loads(db.get_state("modules_enabled"))
    assert "carer" in modules


# ─────────────────────────────────────────────────────────────
#  _push_queue
# ─────────────────────────────────────────────────────────────

def test_push_queue_complete_todo_removes_from_queue():
    db.upsert_todos([{"id": 5, "todo": "Task", "completed": False, "completed_at": None}])
    db.enqueue("complete_todo", {"id": 5})
    with patch("requests.put", return_value=_mock_put(200)):
        _push_queue(BASE, HEADERS)
    assert db.get_queue() == []


def test_push_queue_complete_todo_keeps_in_queue_on_failure():
    db.enqueue("complete_todo", {"id": 6})
    with patch("requests.put", return_value=_mock_put(500)):
        _push_queue(BASE, HEADERS)
    assert len(db.get_queue()) == 1


def test_push_queue_complete_schedule_removes_from_queue():
    db.upsert_schedule([{
        "id": 1, "name": "Meds", "frequency": "daily",
        "day_of_week": None, "scheduled_time": "08:00",
        "last_completed_at": None, "is_active": True,
    }])
    db.enqueue("complete_schedule", {"id": 1})
    with patch("requests.put", return_value=_mock_put(200)):
        _push_queue(BASE, HEADERS)
    assert db.get_queue() == []


def test_push_queue_carer_arrive():
    db.create_carer_visit("Bob", "2026-04-06 10:00:00")
    local_id = db.get_active_carer_visit()["id"]
    db.enqueue("carer_arrive", {
        "local_id": local_id,
        "carer_name": "Bob",
        "arrived_at": "2026-04-06 10:00:00",
    })
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"data": {"id": 77}}
    with patch("requests.post", return_value=mock_resp):
        _push_queue(BASE, HEADERS)
    assert db.get_queue() == []
    visit = db.get_active_carer_visit()
    assert visit["laravel_id"] == 77


def test_push_queue_carer_leave():
    local_id = db.create_carer_visit("Bob", "2026-04-06 10:00:00")
    db.set_carer_visit_laravel_id(local_id, 77)
    db.close_carer_visit(local_id, "2026-04-06 12:00:00")
    db.enqueue("carer_leave", {
        "local_id": local_id,
        "laravel_id": 77,
        "left_at": "2026-04-06 12:00:00",
    })
    with patch("requests.put", return_value=_mock_put(200)):
        _push_queue(BASE, HEADERS)
    assert db.get_queue() == []


# ─────────────────────────────────────────────────────────────
#  _run (full sync cycle)
# ─────────────────────────────────────────────────────────────

def test_run_does_nothing_without_token():
    """If no token in DB, _run should return without making any requests."""
    with patch("requests.get") as mock_get:
        _run()
    mock_get.assert_not_called()


def test_run_sets_last_sync_timestamp():
    db.set_state("api_token", "tok")
    db.set_state("api_base_url", BASE)
    ok_resp = _mock_get({"data": [], "items": [], "alert": None,
                         "layout": {}, "modules_enabled": None, "timezone": "UTC"})
    with patch("requests.get", return_value=ok_resp), \
         patch("requests.put", return_value=_mock_put()):
        _run()
    assert db.get_state("last_sync") is not None
