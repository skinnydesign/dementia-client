"""
Test configuration — sets up a temp SQLite DB and patches sync.start
before any app code is imported, since app.py runs both at module level.
"""
import os
import sys
import tempfile
from unittest.mock import patch

# ── Must happen before app/db/sync are imported ──────────────────────────────
_TEST_DATA_DIR = tempfile.mkdtemp()
os.environ["DATA_DIR"]     = _TEST_DATA_DIR
os.environ["SECRET_KEY"]   = "test-secret-key"
os.environ["API_BASE_URL"] = "http://test-laravel/api"

# Prevent the real background thread from starting during tests
_sync_patcher = patch("sync.start")
_sync_patcher.start()

# ── Now safe to import ────────────────────────────────────────────────────────
import pytest
import db


@pytest.fixture(autouse=True)
def reset_db():
    """Truncate all app tables before every test for a clean slate."""
    import sqlite3
    db.init_db()
    conn = sqlite3.connect(db.DB_PATH)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
    ).fetchall()
    for (t,) in tables:
        conn.execute(f"DELETE FROM [{t}]")
    conn.commit()
    conn.close()


@pytest.fixture
def client():
    import os
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    # app/templates and app/static are empty Docker mount points;
    # point Flask at the real directories one level up.
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    flask_app.template_folder = os.path.join(_root, "templates")
    flask_app.static_folder   = os.path.join(_root, "static")
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def auth_client(client):
    """A test client that is already logged in."""
    with client.session_transaction() as sess:
        sess["api_token"]  = "test-token-abc"
        sess["user_name"]  = "Test User"
        sess["user_email"] = "test@example.com"
    return client
