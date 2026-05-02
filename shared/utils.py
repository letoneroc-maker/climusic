from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
from typing import Iterable, List, Optional

IS_WINDOWS = os.name == "nt"

NOISE_WORDS = {
    "official", "mv", "hd", "4k", "lyrics", "lyric", "audio",
    "完整版", "官方版",
}
NEGATIVE_TERMS = {
    "教学", "教程", "翻唱", "reaction", "react", "vlog", "采访", "解说",
    "鬼畜", "live stream", "直播回放", "cover lesson", "guitar tutorial",
    "piano tutorial", "karaoke", "instrumental",
}


def clean_artist_name(value: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", value or "").strip()


def normalize_title(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    for word in NOISE_WORDS:
        text = text.replace(word, " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def query_tokens(value: str) -> List[str]:
    tokens = re.split(r"[\s/|,]+", (value or "").lower().strip())
    return [token for token in tokens if token]


def matches_negative_term(value: str) -> bool:
    text = (value or "").lower()
    return any(term in text for term in NEGATIVE_TERMS)


def duration_to_seconds(raw: str) -> Optional[int]:
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    parts = [int(part) for part in raw.split(":") if part.isdigit()]
    if not parts:
        return None
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def json_dumps(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def run_subprocess(command: List[str], timeout: int = 90) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("PYTHONWARNINGS", "ignore")
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def recv_json_line(sock: socket.socket) -> dict:
    chunks = []
    while True:
        data = sock.recv(65536)
        if not data:
            break
        chunks.append(data)
        if b"\n" in data:
            break
    raw = b"".join(chunks).split(b"\n", 1)[0].decode("utf-8")
    return json.loads(raw) if raw else {}


def shell_join(parts: Iterable[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)