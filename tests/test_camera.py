"""
Tests for camera.py — status polling and start/stop decisions.
Subprocesses and HTTP are mocked; no camera needed.
"""
from unittest.mock import MagicMock, patch

import camera
from conftest import _camera_patcher
import db


def _status(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def _login():
    db.set_state("api_token", "tok")
    db.set_state("api_base_url", "http://test-laravel/api/")


def _streamer(running=False):
    s = MagicMock(spec=camera.Streamer)
    s.running.return_value = running
    return s


def test_fetch_status_none_when_logged_out():
    with patch("camera.requests.get") as get:
        assert camera._fetch_status() is None
        get.assert_not_called()


def test_fetch_status_calls_laravel_with_token():
    _login()
    with patch("camera.requests.get", return_value=_status({"requested": False})) as get:
        assert camera._fetch_status() == {"requested": False}
    url = get.call_args[0][0]
    assert url == "http://test-laravel/api/camera/status"
    assert get.call_args[1]["headers"]["Authorization"] == "Bearer tok"


def test_fetch_status_none_on_network_error():
    _login()
    with patch("camera.requests.get", side_effect=Exception("offline")):
        assert camera._fetch_status() is None


def test_tick_starts_stream_when_requested():
    s = _streamer(running=False)
    payload = {"requested": True, "viewer_name": "Sarah", "publish_url": "rtsp://x/resident-1"}
    with patch("camera._fetch_status", return_value=payload):
        camera._tick(s)
    s.start.assert_called_once_with("rtsp://x/resident-1")
    assert camera.get_live() == {"live": True, "viewer": "Sarah"}


def test_tick_does_not_restart_running_stream():
    s = _streamer(running=True)
    payload = {"requested": True, "viewer_name": "Sarah", "publish_url": "rtsp://x/resident-1"}
    with patch("camera._fetch_status", return_value=payload):
        camera._tick(s)
    s.start.assert_not_called()


def test_tick_stops_stream_when_not_requested():
    db.set_state("camera_live", "Sarah")
    s = _streamer(running=True)
    with patch("camera._fetch_status", return_value={"requested": False}):
        camera._tick(s)
    s.stop.assert_called_once()
    assert camera.get_live() == {"live": False, "viewer": None}


def test_tick_stops_stream_when_offline():
    s = _streamer(running=True)
    with patch("camera._fetch_status", return_value=None):
        camera._tick(s)
    s.stop.assert_called_once()


def test_streamer_pipes_camera_into_ffmpeg():
    procs = [MagicMock(), MagicMock()]
    with patch("camera._camera_binary", return_value="/usr/bin/rpicam-vid"), \
         patch("camera.subprocess.Popen", side_effect=procs) as popen:
        camera.Streamer().start("rtsp://x/resident-1")
    cam_cmd, ff_cmd = popen.call_args_list[0][0][0], popen.call_args_list[1][0][0]
    assert cam_cmd[0] == "/usr/bin/rpicam-vid"
    assert ff_cmd[0] == "ffmpeg" and ff_cmd[-1] == "rtsp://x/resident-1"
    assert popen.call_args_list[1][1]["stdin"] is procs[0].stdout


def test_start_disabled_without_camera_binary(tmp_path):
    with patch("camera.LOCK_PATH", str(tmp_path / "camera.lock")), \
         patch("camera._camera_binary", return_value=None), \
         patch("camera.threading.Thread") as thread:
        _camera_patcher.temp_original()
    thread.assert_not_called()
