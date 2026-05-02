from __future__ import annotations

import os
import sys

IS_WINDOWS = os.name == "nt"


def _get_pipe_path(name: str) -> str:
    if IS_WINDOWS:
        return rf"\\.\pipe\music-agent\{name}"
    return f"/tmp/music-agent/{name}"


DAEMON_PIPE = _get_pipe_path("musicd")
MPV_PIPE = _get_pipe_path("mpv")


def _get_cache_dir() -> str:
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.environ["USERPROFILE"], "AppData", "Local")
        return os.path.join(base, "music-agent-win")
    return os.path.expanduser("~/.cache/music-agent")


CACHE_DIR = _get_cache_dir()
APP_DIR = _get_cache_dir()


def acquire_lock(lock_path: str, timeout: int = 30) -> int:
    if IS_WINDOWS:
        import msvcrt

        flags = 0
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            fd = os.open(lock_path, flags, 0o644)
            return fd
        except OSError:
            pass
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                fd = os.open(lock_path, flags, 0o644)
                return fd
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("无法获取锁")
    else:
        import fcntl

        fd = open(lock_path, "w")
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd


def release_lock(fd: int) -> None:
    if IS_WINDOWS:
        os.close(fd)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def kill_process(pid: int, force: bool = False) -> None:
    if IS_WINDOWS:
        import subprocess

        sig = "/F" if force else ""
        tree = "/T" if force else ""
        subprocess.run(["taskkill", sig, tree, "/PID", str(pid)], check=False)
    else:
        import signal

        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)


def process_alive(pid: int) -> bool:
    if IS_WINDOWS:
        import subprocess

        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        )
        return str(pid) in result.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def pkill_pattern(pattern: str) -> list[int]:
    if IS_WINDOWS:
        import subprocess

        killed: list[int] = []
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq mpv.exe", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            parts = line.strip().split('","')
            if len(parts) >= 2:
                try:
                    killed.append(int(parts[1].strip('"')))
                except ValueError:
                    pass
        return killed
    else:
        import subprocess

        result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return []
        return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]