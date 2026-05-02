from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from shared.errors import MusicError
from shared.models import Track
from shared.runtime import (
    CURRENT_ART_PATH,
    MPV_PID_PATH,
    MPV_SOCKET_PATH,
    ensure_runtime_dir,
)

IS_WINDOWS = os.name == "nt"


class MpvPlayer:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None

    def _mpv_path(self) -> Optional[str]:
        if IS_WINDOWS:
            for candidate in [shutil.which("mpv"), r"C:\Program Files\mpv\mpv.exe"]:
                if candidate and Path(candidate).exists():
                    return candidate
            return None
        for candidate in [shutil.which("mpv"), "/usr/local/bin/mpv", "/opt/homebrew/bin/mpv"]:
            if candidate and Path(candidate).exists():
                return candidate
        return None

    def _process_alive(self, pid: int) -> bool:
        if IS_WINDOWS:
            try:
                subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    check=False,
                )
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                )
                return str(pid) in result.stdout
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def _cleanup_orphan_mpv(self) -> None:
        if MPV_PID_PATH.exists():
            try:
                pid = int(MPV_PID_PATH.read_text(encoding="utf-8").strip())
                if self._process_alive(pid):
                    self._kill_pid(pid)
                    time.sleep(0.2)
                MPV_PID_PATH.unlink(missing_ok=True)
            except Exception:
                MPV_PID_PATH.unlink(missing_ok=True)

        if IS_WINDOWS:
            self._pkill_mpv_handles()
        else:
            import shared.win_compat as wc

            pids = wc.pkill_pattern(f"--input-ipc-server={MPV_SOCKET_PATH}")
            for pid in pids:
                self._kill_pid(pid)

        if MPV_SOCKET_PATH.exists():
            if IS_WINDOWS:
                try:
                    Path(MPV_SOCKET_PATH).unlink()
                except Exception:
                    pass
            else:
                MPV_SOCKET_PATH.unlink(missing_ok=True)

    def _pkill_mpv_handles(self) -> None:
        import subprocess

        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "mpv.exe"],
                capture_output=True,
                check=False,
            )
        except Exception:
            pass

    def _kill_pid(self, pid: int) -> None:
        if IS_WINDOWS:
            import subprocess

            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False)
        else:
            try:
                import signal

                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    def ensure_started(self) -> None:
        mpv_path = self._mpv_path()
        if mpv_path is None:
            raise MusicError("PLAYER_UNAVAILABLE", "未检测到 mpv，请先安装 mpv")
        ensure_runtime_dir()
        if MPV_PID_PATH.exists():
            try:
                pid = int(MPV_PID_PATH.read_text(encoding="utf-8").strip())
                if self._process_alive(pid) and MPV_SOCKET_PATH.exists():
                    return
            except Exception:
                pass
        if self.process and self.process.poll() is None and MPV_SOCKET_PATH.exists():
            MPV_PID_PATH.write_text(str(self.process.pid), encoding="utf-8")
            return
        self._cleanup_orphan_mpv()

        if IS_WINDOWS:
            ipc_arg = f"{MPV_SOCKET_PATH}"
        else:
            ipc_arg = f"--input-ipc-server={MPV_SOCKET_PATH}"

        command = [
            mpv_path,
            "--idle=yes",
            "--no-video",
            "--force-window=no",
            "--keep-open=no",
            f"--input-ipc-server={MPV_SOCKET_PATH}",
            "--really-quiet",
        ]
        if IS_WINDOWS:
            command = [mpv_path, "--idle=yes", "--no-video", "--force-window=no", "--keep-open=no",
                       f"--input-ipc-server={MPV_SOCKET_PATH}", "--really-quiet"]

        startupinfo = None
        if IS_WINDOWS:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        MPV_PID_PATH.write_text(str(self.process.pid), encoding="utf-8")
        deadline = time.time() + 10
        while time.time() < deadline:
            if MPV_SOCKET_PATH.exists():
                return
            time.sleep(0.1)
        raise MusicError("PLAYER_UNAVAILABLE", "mpv 已启动，但 IPC 未就绪")

    def _send(self, command: list) -> dict:
        self.ensure_started()

        payload = {"command": command, "request_id": int(time.time() * 1000) % 1_000_000}

        if IS_WINDOWS:
            return self._windows_send_ipc(payload)
        return self._unix_send_ipc(payload)

    def _unix_send_ipc(self, payload: dict) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(10)
            client.connect(str(MPV_SOCKET_PATH))
            client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            chunks = []
            while True:
                data = client.recv(65536)
                if not data:
                    break
                chunks.append(data)
                if b"\n" in data:
                    break
        raw = b"".join(chunks).split(b"\n", 1)[0].decode("utf-8")
        return json.loads(raw) if raw else {}

    def _windows_send_ipc(self, payload: dict) -> dict:
        import win32file
        import win32pipe

        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                handle = win32file.CreateFile(
                    MPV_SOCKET_PATH,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None,
                )
                break
            except Exception:
                time.sleep(0.1)

        try:
            data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            win32file.WriteFile(handle, data)
            win32file.FlushFileBuffers(handle)

            _, received = win32file.ReadFile(handle, 65536)
            if received:
                raw = received.decode("utf-8", errors="ignore").split("\n", 1)[0]
                return json.loads(raw) if raw else {}
            return {}
        finally:
            win32file.CloseHandle(handle)

    def load(self, track: Track) -> None:
        response = self._send(["loadfile", track.stream_url, "replace"])
        if response.get("error") not in (None, "success"):
            raise MusicError("PLAYER_UNAVAILABLE", "播放器加载失败")
        self._apply_now_playing_metadata(track)

    def stop(self) -> None:
        self._send(["stop"])
        self._clear_now_playing_metadata()

    def quit(self) -> None:
        try:
            self._send(["quit"])
        except Exception:
            pass

        if MPV_PID_PATH.exists():
            try:
                pid = int(MPV_PID_PATH.read_text(encoding="utf-8").strip())
                if self._process_alive(pid):
                    self._kill_pid(pid)
            except Exception:
                pass

        MPV_PID_PATH.unlink(missing_ok=True)

        if IS_WINDOWS:
            try:
                if Path(MPV_SOCKET_PATH).exists():
                    Path(MPV_SOCKET_PATH).unlink()
            except Exception:
                pass
        else:
            MPV_SOCKET_PATH.unlink(missing_ok=True)

    def set_pause(self, value: bool) -> None:
        self._send(["set_property", "pause", value])

    def set_volume(self, value: int) -> None:
        self._send(["set_property", "volume", value])

    def get_property(self, name: str, default: Any = None) -> Any:
        response = self._send(["get_property", name])
        if response.get("error") not in (None, "success"):
            return default
        return response.get("data", default)

    def is_idle(self) -> bool:
        return bool(self.get_property("idle-active", True))

    def _apply_now_playing_metadata(self, track: Track) -> None:
        title = track.title or "未知歌曲"
        artist = track.artist or "未知歌手"
        display_title = f"{artist} - {title}"
        self._send(["set_property", "force-media-title", display_title])
        art_path = self._download_cover_art(track)
        if art_path:
            self._send(["set_property", "cover-art-files", [art_path]])

    def _clear_now_playing_metadata(self) -> None:
        try:
            self._send(["set_property", "force-media-title", ""])
        except Exception:
            pass
        try:
            self._send(["set_property", "cover-art-files", []])
        except Exception:
            pass

    def _download_cover_art(self, track: Track) -> Optional[str]:
        if not track.thumbnail_url:
            return None
        ensure_runtime_dir()
        suffix = Path(track.thumbnail_url.split("?", 1)[0]).suffix or ".jpg"
        target = CURRENT_ART_PATH.with_suffix(suffix)
        try:
            with urllib.request.urlopen(track.thumbnail_url, timeout=10) as response:
                target.write_bytes(response.read())
            for other in target.parent.glob("current-cover.*"):
                if other != target:
                    other.unlink(missing_ok=True)
            return str(target)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None