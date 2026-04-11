"""
Tests for app.py — all Flask routes.
External Laravel API calls are mocked so tests run without a server.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
import db


# ─────────────────────────────────────────────────────────────
#  Auth / redirect behaviour
# ─────────────────────────────────────────────────────────────

def test_root_unauthenticated_redirects_to_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_root_authenticated_redirects_to_dashboard(auth_client):
    r = auth_client.get("/")
    assert r.status_code == 302
    assert "/dashboard" in r.headers["Location"]


def test_login_page_renders(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert b"login" in r.data.lower()


def test_protected_route_redirects_unauthenticated(client):
    for path in ["/dashboard", "/settings", "/api/todos", "/api/schedule/due",
                 "/api/alert", "/api/ical", "/api/carer/status"]:
        r = client.get(path)
        assert r.status_code == 302, f"{path} should redirect unauthenticated users"
        assert "/login" in r.headers["Location"]


# ─────────────────────────────────────────────────────────────
#  Login POST
# ─────────────────────────────────────────────────────────────

def test_login_success_with_email(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "token": "abc123",
        "user": {"name": "Alice", "email": "alice@example.com"},
    }
    with patch("requests.post", return_value=mock_response) as mock_post, \
         patch("sync.trigger"):
        r = client.post("/login", data={"login": "alice@example.com", "password": "secret"})
    assert r.status_code == 302
    assert "/dashboard" in r.headers["Location"]
    # Should send email field, not username
    assert mock_post.call_args[1]["json"]["email"] == "alice@example.com"
    assert "username" not in mock_post.call_args[1]["json"]


def test_login_success_with_username(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "token": "abc123",
        "user": {"name": "Alice", "email": "alice@example.com"},
    }
    with patch("requests.post", return_value=mock_response) as mock_post, \
         patch("sync.trigger"):
        r = client.post("/login", data={"login": "alice", "password": "secret"})
    assert r.status_code == 302
    assert "/dashboard" in r.headers["Location"]
    # Should send username field, not email
    assert mock_post.call_args[1]["json"]["username"] == "alice"
    assert "email" not in mock_post.call_args[1]["json"]


def test_login_wrong_credentials_shows_error(client):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"message": "Invalid credentials."}
    with patch("requests.post", return_value=mock_response):
        r = client.post("/login", data={"login": "x@x.com", "password": "wrong"})
    assert r.status_code == 200
    assert b"Invalid credentials" in r.data


def test_login_missing_fields_shows_error(client):
    r = client.post("/login", data={"login": "", "password": ""})
    assert r.status_code == 200
    assert b"required" in r.data.lower()


def test_login_api_unreachable_shows_error(client):
    import requests as req
    with patch("requests.post", side_effect=req.exceptions.ConnectionError):
        r = client.post("/login", data={"login": "a@b.com", "password": "pw"})
    assert r.status_code == 200
    assert b"cannot reach" in r.data.lower()


# ─────────────────────────────────────────────────────────────
#  Logout
# ─────────────────────────────────────────────────────────────

def test_logout_clears_session_and_redirects(auth_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("requests.delete", return_value=mock_response):
        r = auth_client.post("/logout")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


# ─────────────────────────────────────────────────────────────
#  Page routes
# ─────────────────────────────────────────────────────────────

def test_dashboard_renders(auth_client):
    r = auth_client.get("/dashboard")
    assert r.status_code == 200


def test_settings_page_renders(auth_client):
    r = auth_client.get("/settings")
    assert r.status_code == 200


def test_wifi_setup_page_is_public(client):
    r = client.get("/wifi-setup")
    assert r.status_code == 200


# ─────────────────────────────────────────────────────────────
#  API — todos
# ─────────────────────────────────────────────────────────────

def test_api_todos_returns_empty_list(auth_client):
    r = auth_client.get("/api/todos")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["todos"] == []


def test_api_todos_returns_cached_todos(auth_client):
    db.upsert_todos([
        {"id": 1, "todo": "Feed cat", "completed": False, "completed_at": None},
        {"id": 2, "todo": "Done task", "completed": True, "completed_at": "2026-04-01"},
    ])
    r = auth_client.get("/api/todos")
    data = r.get_json()
    assert len(data["todos"]) == 2


def test_api_complete_todo_marks_done(auth_client):
    db.upsert_todos([{"id": 3, "todo": "Task", "completed": False, "completed_at": None}])
    with patch("requests.put", return_value=MagicMock(status_code=200)):
        r = auth_client.put("/api/todos/3/complete")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    todos = db.get_todos()
    assert todos[0]["completed"] == 1


def test_api_complete_todo_still_marks_done_when_offline(auth_client):
    """Local completion always happens even if the API push fails."""
    db.upsert_todos([{"id": 4, "todo": "Task", "completed": False, "completed_at": None}])
    import requests as req
    with patch("requests.put", side_effect=req.exceptions.ConnectionError):
        r = auth_client.put("/api/todos/4/complete")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert db.get_todos()[0]["completed"] == 1


# ─────────────────────────────────────────────────────────────
#  API — schedule
# ─────────────────────────────────────────────────────────────

def test_api_schedule_due_returns_empty_when_nothing_due(auth_client):
    r = auth_client.get("/api/schedule/due")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["items"] == []


def test_api_schedule_due_returns_due_items(auth_client):
    from datetime import datetime
    # Insert a daily item that is due now
    db.upsert_schedule([{
        "id": 1, "name": "Morning meds", "frequency": "daily",
        "day_of_week": None, "scheduled_time": "00:01",
        "last_completed_at": None, "is_active": True,
    }])
    r = auth_client.get("/api/schedule/due")
    data = r.get_json()
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Morning meds"


def test_api_schedule_complete(auth_client):
    db.upsert_schedule([{
        "id": 1, "name": "Meds", "frequency": "daily",
        "day_of_week": None, "scheduled_time": "00:01",
        "last_completed_at": None, "is_active": True,
    }])
    with patch("requests.put", return_value=MagicMock(status_code=200)):
        r = auth_client.put("/api/schedule/1/complete")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    items = db.get_schedule_items()
    assert items[0]["last_completed_at"] is not None


# ─────────────────────────────────────────────────────────────
#  API — alert
# ─────────────────────────────────────────────────────────────

def test_api_alert_no_alert(auth_client):
    r = auth_client.get("/api/alert")
    data = r.get_json()
    assert data["ok"] is True
    assert data["alert"] is None


def test_api_alert_active(auth_client):
    from datetime import timedelta
    future = (db._local_now() + timedelta(hours=1)).isoformat()
    db.set_alert("Take your tablets", future)
    r = auth_client.get("/api/alert")
    data = r.get_json()
    assert data["alert"]["message"] == "Take your tablets"
    assert data["alert"]["seconds_remaining"] > 0


# ─────────────────────────────────────────────────────────────
#  API — iCal
# ─────────────────────────────────────────────────────────────

def test_api_ical_empty(auth_client):
    r = auth_client.get("/api/ical")
    data = r.get_json()
    assert data["ok"] is True
    assert data["events"] == []


def test_api_ical_returns_events(auth_client):
    db.replace_ical_events([{
        "summary": "Hospital appt", "date": "2026-04-10",
        "end": None, "time": "10:00", "end_time": None, "location": "City Hospital",
    }])
    r = auth_client.get("/api/ical")
    data = r.get_json()
    assert len(data["events"]) == 1
    assert data["events"][0]["summary"] == "Hospital appt"
    assert data["events"][0]["location"] == "City Hospital"


# ─────────────────────────────────────────────────────────────
#  API — carer visits
# ─────────────────────────────────────────────────────────────

def test_api_carer_status_no_active_visit(auth_client):
    db.set_state("modules_enabled", json.dumps(["carer"]))
    r = auth_client.get("/api/carer/status")
    data = r.get_json()
    assert data["ok"] is True
    assert data["active_visit"] is None


def test_api_carer_arrive_creates_visit(auth_client):
    with patch("requests.post", return_value=MagicMock(
        status_code=201, json=lambda: {"data": {"id": 99}}
    )):
        r = auth_client.post("/api/carer/arrive",
                             json={"carer_name": "Susan"},
                             content_type="application/json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["carer_name"] == "Susan"
    visit = db.get_active_carer_visit()
    assert visit is not None
    assert visit["carer_name"] == "Susan"


def test_api_carer_arrive_requires_name(auth_client):
    r = auth_client.post("/api/carer/arrive",
                         json={"carer_name": ""},
                         content_type="application/json")
    assert r.status_code == 400


def test_api_carer_leave_closes_visit(auth_client):
    local_id = db.create_carer_visit("Susan", "2026-04-06 09:00:00")
    db.set_carer_visit_laravel_id(local_id, 99)
    with patch("requests.put", return_value=MagicMock(status_code=200)):
        r = auth_client.post("/api/carer/leave", content_type="application/json")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert db.get_active_carer_visit() is None


def test_api_carer_leave_no_visit_returns_404(auth_client):
    r = auth_client.post("/api/carer/leave", content_type="application/json")
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────
#  API — force sync
# ─────────────────────────────────────────────────────────────

def test_api_force_sync(auth_client):
    with patch("sync.trigger") as mock_trigger:
        r = auth_client.post("/api/sync")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    mock_trigger.assert_called_once()


# ─────────────────────────────────────────────────────────────
#  WiFi — graceful failures in non-Pi environment
# ─────────────────────────────────────────────────────────────

def test_wifi_scan_returns_json(client):
    r = client.get("/api/wifi/scan")
    # Returns either a list of networks or an error — always JSON
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, (list, dict))


def test_wifi_connect_requires_ssid(client):
    r = client.post("/api/wifi/connect",
                    json={"ssid": "", "password": ""},
                    content_type="application/json")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
