from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"

from musicd.state import PlaybackManager
from shared.errors import MusicError
from shared.runtime import (
    LOCK_PATH,
    LOG_PATH,
    PID_PATH,
    SOCKET_PATH,
    STATUS_JSON_PATH,
    ensure_runtime_dir,
)

MANAGER = PlaybackManager()
SERVER = None

# Use TCP for Windows compatibility
DAEMON_PORT = 18743


def dispatch(payload: dict) -> dict:
    action = payload.get("action")
    if action == "play":
        return MANAGER.play_keyword(payload.get("query", ""))
    if action == "hot":
        return MANAGER.play_hot(payload.get("lang"))
    if action == "pause":
        return MANAGER.pause()
    if action == "resume":
        return MANAGER.resume()
    if action == "next":
        return MANAGER.next_track()
    if action == "prev":
        return MANAGER.prev_track()
    if action == "stop":
        return MANAGER.stop()
    if action == "shutdown":
        response = MANAGER.shutdown()
        if SERVER is not None:
            threading.Thread(target=lambda: SERVER.shutdown(), daemon=True).start()
        return response
    if action == "status":
        return MANAGER.status()
    if action == "volume":
        return MANAGER.set_volume(int(payload["value"]))
    if action == "volume_up":
        return MANAGER.volume_up()
    if action == "volume_down":
        return MANAGER.volume_down()
    if action == "mute":
        return MANAGER.mute()
    if action == "unmute":
        return MANAGER.unmute()
    if action == "lang":
        return MANAGER.set_lang(payload.get("value"))
    if action == "source":
        return MANAGER.set_source(payload.get("value"))
    raise MusicError("INVALID_ARGUMENT", f"不支持的命令：{action}")


def json_dumps(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def _run_server_windows() -> None:
    global SERVER

    ensure_runtime_dir()
    try:
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
    except Exception:
        pass

    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    MANAGER.start_monitor()

    import socket

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", DAEMON_PORT))
    server_sock.listen(10)
    server_sock.settimeout(1.0)

    class Handler:
        def __init__(self, client_sock, addr):
            self.sock = client_sock
            self.addr = addr

        def handle(self):
            try:
                self.sock.settimeout(30)
                data = b""
                while b"\n" not in data:
                    chunk = self.sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) > 65536:
                        break

                if not data:
                    return

                raw = data.decode("utf-8", errors="ignore").split("\n", 1)[0].strip()
                if not raw:
                    return

                try:
                    payload = json.loads(raw)
                    response = dispatch(payload)
                except MusicError as exc:
                    response = exc.to_dict()
                except Exception as exc:
                    response = {"ok": False, "error_code": "INTERNAL_ERROR", "message": str(exc)}

                reply = json_dumps(response)
                self.sock.sendall(reply)
            except Exception:
                pass
            finally:
                try:
                    self.sock.close()
                except Exception:
                    pass

    SERVER = server_sock

    while True:
        try:
            client_sock, addr = server_sock.accept()
            handler = Handler(client_sock, addr)
            t = threading.Thread(target=lambda: handler.handle(), daemon=True)
            t.start()
        except socket.timeout:
            continue
        except Exception:
            if SERVER is None:
                break
            time.sleep(0.1)


def _run_server_unix() -> None:
    global SERVER

    ensure_runtime_dir()
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    MANAGER.start_monitor()

    import socketserver

    class RequestHandler(socketserver.StreamRequestHandler):
        def handle(self):
            raw = self.rfile.readline().decode("utf-8").strip()
            if not raw:
                return
            try:
                payload = json.loads(raw)
                response = dispatch(payload)
            except MusicError as exc:
                response = exc.to_dict()
            except Exception as exc:
                response = {"ok": False, "error_code": "INTERNAL_ERROR", "message": str(exc)}
            try:
                self.wfile.write(json_dumps(response))
            except BrokenPipeError:
                pass

    class ThreadedUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    with ThreadedUnixServer(str(SOCKET_PATH), RequestHandler) as server:
        SERVER = server
        server.serve_forever()


def run_server() -> None:
    if IS_WINDOWS:
        _run_server_windows()
    else:
        _run_server_unix()


def _is_pid_alive(pid: int) -> bool:
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


def daemonize() -> None:
    ensure_runtime_dir()

    if IS_WINDOWS:
        _daemonize_windows()
    else:
        _daemonize_unix()


def _daemonize_unix() -> None:
    import fcntl

    with open(LOCK_PATH, "w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if SOCKET_PATH.exists():
            return
        if PID_PATH.exists():
            try:
                pid = int(PID_PATH.read_text(encoding="utf-8").strip())
                os.kill(pid, 0)
                deadline = time.time() + 5
                while time.time() < deadline:
                    if SOCKET_PATH.exists():
                        return
                    time.sleep(0.1)
            except Exception:
                try:
                    PID_PATH.unlink()
                except FileNotFoundError:
                    pass
        with open(LOG_PATH, "a", encoding="utf-8") as log_file, open(os.devnull, "rb") as null_in:
            from subprocess import Popen
            Popen(
                [sys.executable, "-m", "musicd.daemon", "--serve"],
                stdout=log_file, stderr=log_file, stdin=null_in,
                start_new_session=True,
                cwd=str(Path(__file__).resolve().parents[1]),
            )
        deadline = time.time() + 10
        while time.time() < deadline:
            if SOCKET_PATH.exists():
                return
            time.sleep(0.1)
    raise MusicError("DAEMON_UNAVAILABLE", "musicd 启动失败，请查看日志")


def _daemonize_windows() -> None:
    import subprocess

    # Check if already running via TCP port
    test_sock = None
    try:
        import socket
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(1)
        test_sock.connect(("127.0.0.1", DAEMON_PORT))
        test_sock.close()
        return  # already running
    except Exception:
        if test_sock:
            test_sock.close()

    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text(encoding="utf-8").strip())
            if _is_pid_alive(pid):
                return
        except Exception:
            pass

    try:
        PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE

    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "musicd.daemon", "--serve"],
            stdout=log_file, stderr=log_file,
            stdin=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=0x08000000,
            cwd=str(Path(__file__).resolve().parents[1]),
        )

    PID_PATH.write_text(str(proc.pid), encoding="utf-8")

    deadline = time.time() + 15
    while time.time() < deadline:
        sock = None
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(("127.0.0.1", DAEMON_PORT))
            sock.close()
            return
        except Exception:
            if sock:
                sock.close()
            time.sleep(0.2)

    raise MusicError("DAEMON_UNAVAILABLE", "musicd 启动失败，请查看日志")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args(argv)
    if args.serve:
        run_server()
        return 0
    daemonize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())