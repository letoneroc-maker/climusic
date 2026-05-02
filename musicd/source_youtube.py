from __future__ import annotations

import json
from urllib.parse import quote
from typing import List

from musicd.source_base import SourceAdapter
from shared.environment import get_yt_dlp_command
from shared.models import Track
from shared.utils import clean_artist_name, run_subprocess


class YouTubeAdapter(SourceAdapter):
    source_name = "youtube"

    def search(self, query: str, limit: int) -> List[Track]:
        base_command = get_yt_dlp_command()
        if not base_command:
            return []
        music_search_url = f"https://music.youtube.com/search?q={quote(query)}"
        command = base_command + [
            "--flat-playlist", "--dump-single-json", music_search_url,
        ]
        result = run_subprocess(command, timeout=40)
        if result.returncode != 0 or not result.stdout.strip():
            fallback_command = base_command + [
                "--flat-playlist", "--dump-single-json", f"ytsearch{limit}:{query}",
            ]
            result = run_subprocess(fallback_command, timeout=40)
            if result.returncode != 0 or not result.stdout.strip():
                return []
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        tracks: List[Track] = []
        for index, entry in enumerate(payload.get("entries", []) or []):
            if entry.get("ie_key") != "Youtube":
                continue
            video_id = entry.get("id")
            if not video_id:
                continue
            title = entry.get("title") or ""
            if not title.strip():
                continue
            url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
            if "watch?v=" not in url:
                continue
            tracks.append(Track(
                id=video_id,
                title=title,
                artist=clean_artist_name(entry.get("channel") or entry.get("uploader") or ""),
                source=self.source_name,
                page_url=url,
                thumbnail_url=(entry.get("thumbnails") or [{}])[-1].get("url"),
                rank_score=max(0.0, 3.0 - (index * 0.05)),
            ))
            if len(tracks) >= limit:
                break
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
            raise RuntimeError(result.stderr.strip() or "youtube resolve failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError("youtube resolve failed: invalid JSON")
        formats = payload.get("formats") or []
        audio_formats = [item for item in formats if item.get("url") and item.get("vcodec") == "none"]
        best = audio_formats[-1] if audio_formats else {}
        stream_url = best.get("url") or payload.get("url")
        if not stream_url:
            raise RuntimeError("no playable youtube stream")
        track.duration_sec = payload.get("duration") or track.duration_sec
        track.thumbnail_url = payload.get("thumbnail") or track.thumbnail_url
        track.artist = clean_artist_name(payload.get("artist") or payload.get("channel") or payload.get("uploader") or track.artist)
        track.title = payload.get("title") or track.title
        return stream_url