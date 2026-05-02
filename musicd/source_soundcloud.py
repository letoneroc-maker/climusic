from __future__ import annotations

import json
from typing import List

from musicd.source_base import SourceAdapter
from shared.environment import get_yt_dlp_command
from shared.models import Track
from shared.utils import clean_artist_name, run_subprocess


class SoundCloudAdapter(SourceAdapter):
    source_name = "soundcloud"

    def search(self, query: str, limit: int) -> List[Track]:
        base_command = get_yt_dlp_command()
        if not base_command:
            return []
        command = base_command + [
            "--flat-playlist", "--dump-single-json", f"scsearch{limit}:{query}",
        ]
        result = run_subprocess(command, timeout=40)
        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        tracks: List[Track] = []
        for entry in payload.get("entries", []) or []:
            track_id = entry.get("id")
            url = entry.get("webpage_url") or entry.get("url")
            if not track_id or not url:
                continue
            tracks.append(Track(
                id=str(track_id),
                title=entry.get("title") or "",
                artist=clean_artist_name(entry.get("uploader") or ""),
                source=self.source_name,
                page_url=url,
                duration_sec=entry.get("duration"),
                thumbnail_url=(entry.get("thumbnails") or [{}])[-1].get("url"),
            ))
        return tracks

    def resolve_stream(self, track: Track) -> str:
        base_command = get_yt_dlp_command()
        if not base_command:
            raise RuntimeError("yt-dlp unavailable")
        command = base_command + [
            "-f", "bestaudio/best", "--no-playlist", "-J", track.page_url,
        ]
        result = run_subprocess(command, timeout=45)
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(result.stderr.strip() or "soundcloud resolve failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError("soundcloud resolve failed: invalid JSON")
        formats = payload.get("formats") or []
        audio_formats = [item for item in formats if item.get("url") and item.get("vcodec") == "none"]
        best = audio_formats[-1] if audio_formats else {}
        stream_url = best.get("url") or payload.get("url")
        if not stream_url:
            raise RuntimeError("no playable soundcloud stream")
        track.duration_sec = payload.get("duration") or track.duration_sec
        track.thumbnail_url = payload.get("thumbnail") or track.thumbnail_url
        track.artist = clean_artist_name(payload.get("artist") or payload.get("uploader") or track.artist)
        track.title = payload.get("title") or track.title
        return stream_url