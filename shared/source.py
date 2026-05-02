from __future__ import annotations

from typing import Dict, Optional


SOURCES: Dict[str, dict] = {
    "youtube": {
        "display": "YouTube Music",
        "aliases": {"y", "yt", "youtube", "youtube music", "ytmusic"},
    },
    "bilibili": {
        "display": "Bilibili",
        "aliases": {"b", "bili", "bilibili"},
    },
    "soundcloud": {
        "display": "SoundCloud",
        "aliases": {"s", "sc", "soundcloud"},
    },
}

DEFAULT_SOURCE = "youtube"


def normalize_source(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    candidate = value.strip().lower()
    if not candidate:
        return None
    for key, spec in SOURCES.items():
        aliases = {alias.lower() for alias in spec["aliases"]}
        if candidate == key or candidate in aliases:
            return key
    return None


def display_source(source_key: str) -> str:
    return SOURCES.get(source_key, SOURCES[DEFAULT_SOURCE])["display"]