from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from shared.models import Track
from shared.utils import clean_artist_name, run_subprocess


def _get_yt_dlp() -> Optional[List[str]]:
    import shutil
    python = sys.executable

    # Try direct yt-dlp command first
    ytdlp = shutil.which("yt-dlp")
    if ytdlp:
        return [ytdlp]

    # Try in Scripts
    scripts = Path(python).parent / "Scripts" / "yt-dlp.exe"
    if scripts.exists():
        return [str(scripts)]

    # Try python -m yt_dlp
    result = run_subprocess([python, "-m", "yt_dlp", "--version"], timeout=10)
    if result.returncode == 0:
        return [python, "-m", "yt_dlp"]

    return None


def search_youtube(query: str, limit: int = 5) -> List[Track]:
    cmd = _get_yt_dlp()
    if not cmd:
        return []

    command = cmd + ["--flat-playlist", "--dump-single-json", f"ytsearch{limit}:{query}"]
    result = run_subprocess(command, timeout=40)
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    tracks = []
    for entry in payload.get("entries", []) or []:
        if entry.get("ie_key") != "Youtube":
            continue
        video_id = entry.get("id")
        if not video_id:
            continue
        title = entry.get("title") or ""
        if not title.strip():
            continue
        url = entry.get("url")
        if not url and "watch?v=" in str(entry):
            url = f"https://www.youtube.com/watch?v={video_id}"

        tracks.append(Track(
            id=video_id,
            title=title,
            artist=clean_artist_name(entry.get("channel") or entry.get("uploader") or ""),
            source="youtube",
            page_url=url or f"https://www.youtube.com/watch?v={video_id}",
            thumbnail_url=(entry.get("thumbnails") or [{}])[-1].get("url"),
        ))
    return tracks[:limit]


def resolve_stream(track: Track) -> str:
    cmd = _get_yt_dlp()
    if not cmd:
        raise RuntimeError("yt-dlp not found")

    command = cmd + ["-f", "bestaudio/best", "--no-playlist", "-J", track.page_url]
    result = run_subprocess(command, timeout=45)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"resolve failed: {result.stderr}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("invalid JSON from yt-dlp")

    formats = payload.get("formats") or []
    audio_formats = [f for f in formats if f.get("url") and f.get("vcodec") == "none"]
    best = audio_formats[-1] if audio_formats else {}
    stream_url = best.get("url") or payload.get("url")
    if not stream_url:
        raise RuntimeError("no playable stream")

    track.duration_sec = payload.get("duration") or track.duration_sec
    track.thumbnail_url = payload.get("thumbnail") or track.thumbnail_url
    track.title = payload.get("title") or track.title
    track.artist = clean_artist_name(
        payload.get("artist") or payload.get("channel") or payload.get("uploader") or track.artist
    )
    return stream_url


def search_bilibili(query: str, limit: int = 5) -> List[Track]:
    import html
    import re

    try:
        from urllib.request import Request, urlopen
    except Exception:
        return []

    url = f"https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={query}&page=1"
    result = run_subprocess(
        ["curl", "-sL", url,
         "-H", "User-Agent: Mozilla/5.0",
         "-H", "Referer: https://www.bilibili.com"],
        timeout=20,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    if payload.get("code") not in (None, 0):
        return []

    tracks = []
    for item in payload.get("data", {}).get("result", []):
        bvid = item.get("bvid")
        if not bvid:
            continue
        title = html.unescape(item.get("title", ""))
        title = title.replace('<em class="keyword">', "").replace("</em>", "")
        tracks.append(Track(
            id=bvid,
            title=title,
            artist=clean_artist_name(item.get("author") or ""),
            source="bilibili",
            page_url=f"https://www.bilibili.com/video/{bvid}",
            duration_sec=_parse_duration(item.get("duration", "")),
            thumbnail_url=item.get("pic"),
        ))
        if len(tracks) >= limit:
            break
    return tracks


def _parse_duration(s: str) -> Optional[int]:
    if not s:
        return None
    parts = s.split(":")
    if len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
    return None


def search_soundcloud(query: str, limit: int = 5) -> List[Track]:
    cmd = _get_yt_dlp()
    if not cmd:
        return []

    command = cmd + ["--flat-playlist", "--dump-single-json", f"scsearch{limit}:{query}"]
    result = run_subprocess(command, timeout=40)
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    tracks = []
    for entry in payload.get("entries", []) or []:
        track_id = entry.get("id")
        url = entry.get("webpage_url") or entry.get("url")
        if not track_id or not url:
            continue
        tracks.append(Track(
            id=str(track_id),
            title=entry.get("title") or "",
            artist=clean_artist_name(entry.get("uploader") or ""),
            source="soundcloud",
            page_url=url,
            duration_sec=entry.get("duration"),
            thumbnail_url=(entry.get("thumbnails") or [{}])[-1].get("url"),
        ))
    return tracks[:limit]


def search_all(query: str, limit: int = 10) -> List[Track]:
    results = []

    for adapter_fn, name in [
        (lambda q, n: search_youtube(q, n), "youtube"),
        (lambda q, n: search_bilibili(q, n), "bilibili"),
        (lambda q, n: search_soundcloud(q, n), "soundcloud"),
    ]:
        try:
            tracks = adapter_fn(query, limit)
            results.extend(tracks)
        except Exception:
            pass

    # Simple deduplication by id+source
    seen = set()
    unique = []
    for t in results:
        key = (t.source, t.id)
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique[:limit]