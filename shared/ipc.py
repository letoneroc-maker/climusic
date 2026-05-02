from __future__ import annotations

import json
import os
import socket
import time
from typing import Any

IS_WINDOWS = os.name == "nt"

DAEMON_PORT = 18743


def send_request(payload: dict, timeout: float = 20) -> dict:
    if IS_WINDOWS:
        return _tcp_send_request(payload, timeout)
    return _unix_send_request(payload, timeout)


def _unix_send_request(payload: dict, timeout: float) -> dict:
    from shared.runtime import SOCKET_PATH
    from shared.utils import json_dumps, recv_json_line

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(SOCKET_PATH))
        client.sendall(json_dumps(payload))
        return recv_json_line(client)


def _tcp_send_request(payload: dict, timeout: float) -> dict:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(("127.0.0.1", DAEMON_PORT))
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        sock.sendall(data)
        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
                if len(chunks) > 20:
                    break
            except socket.timeout:
                break
        raw = b"".join(chunks).decode("utf-8", errors="ignore").split("\n", 1)[0]
        return json.loads(raw) if raw else {}
    finally:
        sock.close()