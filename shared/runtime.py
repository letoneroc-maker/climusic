from __future__ import annotations

import os
from pathlib import Path

IS_WINDOWS = os.name == "nt"


def _get_cache_dir() -> Path:
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.environ["USERPROFILE"], "AppData", "Local")
        return Path(base) / "music-agent-win"
    return Path.home() / ".cache" / "music-agent"


APP_DIR: Path = _get_cache_dir()
ARTWORK_DIR = APP_DIR / "artwork"

if IS_WINDOWS:
    SOCKET_PATH: Path = Path(r"\\.\pipe\music-agent\musicd")
    PID_PATH = APP_DIR / "musicd.pid"
    LOG_PATH = APP_DIR / "musicd.log"
    MPV_SOCKET_PATH: Path = Path(r"\\.\pipe\music-agent\mpv")
    MPV_PID_PATH = APP_DIR / "mpv.pid"
    LOCK_PATH = APP_DIR / "musicd.lock"
else:
    SOCKET_PATH = Path("/tmp/music-agent/musicd.sock")
    PID_PATH = APP_DIR / "musicd.pid"
    LOG_PATH = APP_DIR / "musicd.log"
    MPV_SOCKET_PATH = Path("/tmp/music-agent/mpv.sock")
    MPV_PID_PATH = APP_DIR / "mpv.pid"
    LOCK_PATH = APP_DIR / "musicd.lock"

STATUS_JSON_PATH = APP_DIR / "status.json"
CURRENT_ART_PATH = ARTWORK_DIR / "current-cover"


def ensure_runtime_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    ARTWORK_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR