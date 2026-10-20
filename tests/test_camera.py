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
    s = _streamer()
    s.running.side_effect = [False, True]  # not running, then running after start
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


def test_tick_hides_badge_when_pipeline_fails_to_start():
    db.set_state("camera_live", "Sarah")
    s = _streamer(running=False)
    payload = {"requested": True, "viewer_name": "Sarah", "publish_url": "rtsp://x/resident-1"}
    with patch("camera._fetch_status", return_value=payload):
        camera._tick(s)
    s.start.assert_called_once()
    assert camera.get_live() == {"live": False, "viewer": None}


def test_tick_waits_while_backing_off():
    s = _streamer(running=False)
    s.can_start.return_value = False
    payload = {"requested": True, "viewer_name": "Sarah", "publish_url": "rtsp://x/resident-1"}
    with patch("camera._fetch_status", return_value=payload):
        camera._tick(s)
    s.start.assert_not_called()
    assert camera.get_live()["live"] is False


def test_backoff_doubles_on_quick_failures_and_caps():
    s = camera.Streamer()
    with patch("camera.time.monotonic") as now:
        now.return_value = 100.0
        assert s.can_start()                     # never started
        waits = []
        for _ in range(6):
            s.started_at = now.return_value      # started, then died straight away
            assert not s.can_start()
            waits.append(s.backoff)
            now.return_value += s.backoff
            assert s.can_start()
    assert waits == [5, 10, 20, 40, 60, 60]


def test_backoff_resets_after_stable_stream():
    s = camera.Streamer()
    s.backoff = 40
    with patch("camera.time.monotonic", return_value=1000.0):
        s.started_at = 1000.0 - camera.STABLE_AFTER - 1
        assert s.can_start()
    assert s.backoff == 0


def test_watch_logs_unexpected_exit(caplog):
    proc = MagicMock()
    proc.stderr = [b"Connection refused\n"]
    proc.wait.return_value = 1
    del proc.stopped
    with patch("camera.threading.Thread") as thread:
        camera._watch(proc, "ffmpeg")
    thread.call_args[1]["target"]()
    assert "ffmpeg exited (code 1): Connection refused" in caplog.text


def test_watch_quiet_when_stopped_on_purpose(caplog):
    proc = MagicMock()
    proc.stderr = []
    proc.stopped = True
    with patch("camera.threading.Thread") as thread:
        camera._watch(proc, "ffmpeg")
    thread.call_args[1]["target"]()
    assert "exited" not in caplog.text


def test_backoff_survives_restart():
    procs = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    s = camera.Streamer()
    with patch("camera._camera_binary", return_value="/usr/bin/rpicam-vid"), \
         patch("camera._watch"), \
         patch("camera.subprocess.Popen", side_effect=procs), \
         patch("camera.time.monotonic", return_value=100.0):
        s.start("rtsp://x/resident-1")
        assert not s.can_start()                 # died straight away
        s.start("rtsp://x/resident-1")
        assert not s.can_start()
    assert s.backoff == 10
