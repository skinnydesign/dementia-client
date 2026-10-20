"""
Camera streaming — pushes the Pi Camera to the MediaMTX relay on demand.

Polls Laravel every few seconds. While a family member/carer has the camera
page open, Laravel reports `requested: true` plus a short-lived publish URL;
we pipe rpicam-vid's H.264 output through ffmpeg to that RTSP URL. When the
viewer goes away we stop. The current viewer is written to sync_state so any
gunicorn worker can show the kiosk's "Camera on" badge.
"""

from __future__ import annotations

import collections
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
MAX_BACKOFF   = 60  # longest wait before restarting a pipeline that keeps dying
STABLE_AFTER  = 30  # a stream that lasted this long resets the backoff

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
        self.cam        = None
        self.ffmpeg     = None
        self.url        = None
        self.started_at = None
        self.backoff    = 0
        self.retry_at   = 0.0

    def can_start(self) -> bool:
        """False while backing off from a pipeline that died soon after starting."""
        if self.started_at is not None:
            # Previous run died — back off if it didn't last long
            if time.monotonic() - self.started_at < STABLE_AFTER:
                self.backoff = min(max(self.backoff * 2, POLL_INTERVAL), MAX_BACKOFF)
            else:
                self.backoff = 0
            self.retry_at   = time.monotonic() + self.backoff
            self.started_at = None
            if self.backoff:
                log.warning("Camera stream died — retrying in %ss.", self.backoff)
        return time.monotonic() >= self.retry_at

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
                                    stderr=subprocess.PIPE, start_new_session=True)
        self.ffmpeg = subprocess.Popen(ff_cmd, stdin=self.cam.stdout,
                                       stderr=subprocess.PIPE, start_new_session=True)
        self.cam.stdout.close()  # ffmpeg owns the pipe now
        _watch(self.cam, "rpicam-vid")
        _watch(self.ffmpeg, "ffmpeg")
        self.url = url
        self.started_at = time.monotonic()
        log.info("Camera stream started.")

    def stop(self) -> None:
        for proc in (self.ffmpeg, self.cam):
            if proc is None or proc.poll() is not None:
                continue
            proc.stopped = True  # tells _watch not to report this exit
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
        self.cam = self.ffmpeg = self.url = self.started_at = None


def _watch(proc, name: str) -> None:
    """Drain a process's stderr and log its last lines if it exits unexpectedly."""
    def run():
        tail = collections.deque(maxlen=5)
        for line in proc.stderr:
            tail.append(line.decode(errors="replace").rstrip())
        code = proc.wait()
        if not getattr(proc, "stopped", False):
            log.warning("%s exited (code %s): %s", name, code, " | ".join(tail) or "no output")
    threading.Thread(target=run, daemon=True, name=f"camera-{name}").start()


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
        if not streamer.running() and streamer.can_start():
            # Not yet started, or the pipeline died — (re)start with a fresh URL
            streamer.start(status["publish_url"])
        # Only show the kiosk badge while frames are actually being sent
        if streamer.running():
            db.set_state("camera_live", status.get("viewer_name") or "Someone")
        else:
            db.set_state("camera_live", None)
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
