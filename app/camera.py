"""
Camera streaming — pushes the Pi Camera to the MediaMTX relay on demand.

Polls Laravel every few seconds. While a family member/carer has the camera
page open, Laravel reports `requested: true` plus a short-lived publish URL;
we pipe rpicam-vid's H.264 output through ffmpeg to that RTSP URL. When the
viewer goes away we stop. The current viewer is written to sync_state so any
gunicorn worker can show the kiosk's "Camera on" badge.
"""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import signal as _signal
import subprocess
import threading
import time

import requests

import db

log = logging.getLogger(__name__)

POLL_INTERVAL = 5   # seconds between Laravel status checks

WIDTH, HEIGHT, FPS = 1280, 720, 15

LOCK_PATH = os.path.join(
    os.environ.get("DATA_DIR", os.path.expanduser("~")), "camera.lock"
)

_lock_file = None   # held open for the life of the owning worker


# ─────────────────────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────────────────────

def start() -> None:
    """Start the camera thread — only one gunicorn worker wins the lock."""
    global _lock_file
    try:
        _lock_file = open(LOCK_PATH, "w")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.info("Camera thread owned by another worker.")
        return

    if not _camera_binary():
        log.info("No rpicam-vid/libcamera-vid found — camera streaming disabled.")
        db.set_state("camera_live", None)
        return

    db.set_state("camera_live", None)
    threading.Thread(target=_loop, daemon=True, name="camera").start()
    log.info("Camera thread started.")


def get_live() -> dict:
    viewer = db.get_state("camera_live")
    return {"live": bool(viewer), "viewer": viewer or None}


# ─────────────────────────────────────────────────────────────
#  LOOP
# ─────────────────────────────────────────────────────────────

class Streamer:
    """Owns the rpicam-vid | ffmpeg pipeline."""

    def __init__(self):
        self.cam    = None
        self.ffmpeg = None
        self.url    = None

    def running(self) -> bool:
        return (self.cam is not None and self.cam.poll() is None
                and self.ffmpeg is not None and self.ffmpeg.poll() is None)

    def start(self, url: str) -> None:
        self.stop()
        cam_cmd = [
            _camera_binary(), "-t", "0", "-n", "--inline",
            "--width", str(WIDTH), "--height", str(HEIGHT),
            "--framerate", str(FPS), "--codec", "h264", "-o", "-",
        ]
        ff_cmd = [
            "ffmpeg", "-loglevel", "error", "-fflags", "nobuffer",
            "-f", "h264", "-framerate", str(FPS), "-i", "-",
            "-c", "copy", "-rtsp_transport", "tcp", "-f", "rtsp", url,
        ]
        self.cam = subprocess.Popen(cam_cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
        self.ffmpeg = subprocess.Popen(ff_cmd, stdin=self.cam.stdout,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
        self.cam.stdout.close()  # ffmpeg owns the pipe now
        self.url = url
        log.info("Camera stream started.")

    def stop(self) -> None:
        for proc in (self.ffmpeg, self.cam):
            if proc is None or proc.poll() is not None:
                continue
            try:
                os.killpg(proc.pid, _signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(proc.pid, _signal.SIGKILL)
                except Exception:
                    pass
        if self.cam or self.ffmpeg:
            log.info("Camera stream stopped.")
        self.cam = self.ffmpeg = self.url = None


def _loop() -> None:
    streamer = Streamer()
    while True:
        try:
            _tick(streamer)
        except Exception as e:
            log.warning(f"Camera tick failed: {e}")
        time.sleep(POLL_INTERVAL)


def _tick(streamer: Streamer) -> None:
    status = _fetch_status()

    if status and status.get("requested") and status.get("publish_url"):
        if not streamer.running():
            # Not yet started, or the pipeline died — (re)start with a fresh URL
            streamer.start(status["publish_url"])
        db.set_state("camera_live", status.get("viewer_name") or "Someone")
    else:
        # Offline or no viewer — never stream without Laravel's say-so
        streamer.stop()
        db.set_state("camera_live", None)


def _fetch_status() -> dict | None:
    token    = db.get_state("api_token")
    base_url = db.get_state("api_base_url")
    if not token or not base_url:
        return None
    try:
        r = requests.get(
            f"{base_url.rstrip('/')}/camera/status",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=5,
        )
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _camera_binary() -> str | None:
    # Bookworm ships rpicam-vid; Bullseye uses the older libcamera-vid name
    return shutil.which("rpicam-vid") or shutil.which("libcamera-vid")
