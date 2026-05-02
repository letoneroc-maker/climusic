from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

IS_WINDOWS = os.name == "nt"

MPV_PIPE = r"\\.\pipe\mpv-media" if IS_WINDOWS else "/tmp/mpv-media"
DAEMON_PORT = 18743


class SimplePlayer:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.queue: list = []
        self.lock = threading.Lock()
        self.current_index = 0
        self.state = "idle"
        self.current_track = None
        self.mpv_socket_path = None

    def _find_mpv(self) -> Optional[str]:
        if IS_WINDOWS:
            for p in [r"C:\Program Files\mpv\mpv.exe", shutil.which("mpv")]:
                if p and Path(p).exists():
                    return p
            return None
        for p in [shutil.which("mpv"), "/usr/local/bin/mpv"]:
            if p and Path(p).exists():
                return p
        return None

    def ensure_started(self) -> None:
        if self.process and self.process.poll() is None:
            return
        mpv = self._find_mpv()
        if not mpv:
            raise RuntimeError("mpv not found")

        if IS_WINDOWS:
            self.mpv_socket_path = MPV_PIPE
            try:
                Path(self.mpv_socket_path).unlink(missing_ok=True)
            except Exception:
                pass
        else:
            self.mpv_socket_path = f"/tmp/mpv-{os.getpid()}.sock"
            try:
                Path(self.mpv_socket_path).unlink(missing_ok=True)
            except Exception:
                pass

        startupinfo = None
        if IS_WINDOWS:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        self.process = subprocess.Popen(
            [mpv, "--idle=yes", "--no-video", "--force-window=no",
             f"--input-ipc-server={self.mpv_socket_path}",
             "--really-quiet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=0x08000000 if IS_WINDOWS else 0,
        )
        # Wait for socket
        deadline = time.time() + 10
        while time.time() < deadline:
            if Path(self.mpv_socket_path).exists() if IS_WINDOWS else os.path.exists(self.mpv_socket_path):
                return
            time.sleep(0.1)

    def _send_mpv(self, cmd: list) -> dict:
        self.ensure_started()

        payload = json.dumps({"command": cmd, "request_id": int(time.time() * 1000) % 1_000_000})

        if IS_WINDOWS:
            return self._send_mpv_windows(payload)
        return self._send_mpv_unix(payload)

    def _send_mpv_unix(self, payload: str) -> dict:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(self.mpv_socket_path)
        s.sendall((payload + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        raw = data.decode("utf-8", errors="ignore").split("\n", 1)[0]
        return json.loads(raw) if raw else {}

    def _send_mpv_windows(self, payload: str) -> dict:
        import win32file, win32pipe

        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                handle = win32file.CreateFile(
                    self.mpv_socket_path,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None
                )
                break
            except Exception:
                time.sleep(0.2)
                continue

        try:
            win32file.WriteFile(handle, (payload + "\n").encode("utf-8"))
            win32file.FlushFileBuffers(handle)
            _, data = win32file.ReadFile(handle, 65536)
            raw = data.decode("utf-8", errors="ignore").split("\n", 1)[0]
            return json.loads(raw) if raw else {}
        finally:
            win32file.CloseHandle(handle)

    def load_url(self, url: str, title: str = "music") -> bool:
        try:
            self.ensure_started()
            self._send_mpv(["loadfile", url, "replace"])
            self._send_mpv(["set_property", "force-media-title", title])
            self.state = "playing"
            self.current_track = {"url": url, "title": title}
            return True
        except Exception as e:
            print(f"load_url error: {e}")
            return False

    def stop(self) -> None:
        try:
            self._send_mpv(["stop"])
        except Exception:
            pass
        self.state = "idle"

    def pause(self) -> None:
        try:
            self._send_mpv(["set_property", "pause", True])
            self.state = "paused"
        except Exception:
            pass

    def resume(self) -> None:
        try:
            self._send_mpv(["set_property", "pause", False])
            self.state = "playing"
        except Exception:
            pass

    def is_playing(self) -> bool:
        try:
            resp = self._send_mpv(["get_property", "pause"])
            return resp.get("data") is not True
        except Exception:
            return False


import shutil