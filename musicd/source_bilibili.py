from __future__ import annotations

import html
import json
import re
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import List

from musicd.source_base import SourceAdapter
from shared.environment import get_yt_dlp_command
from shared.models import Track
from shared.utils import clean_artist_name, duration_to_seconds, run_subprocess


class BilibiliAdapter(SourceAdapter):
    source_name = "bilibili"
    _RESULT_PATTERN = re.compile(
        r'bvid:"(?P<bvid>(?:\\.|[^"\\])+)".*?title:"(?P<title>(?:\\.|[^"\\])*)".*?author:"(?P<author>(?:\\.|[^"\\])*)".*?duration:"(?P<duration>(?:\\.|[^"\\])*)".*?pic:"(?P<pic>(?:\\.|[^"\\])*)"',
        re.S,
    )

    def search(self, query: str, limit: int) -> List[Track]:
        tracks = self._search_webpage(query, limit)
        if tracks:
            return tracks[:limit]
        return self._search_api(query, limit)

    def _search_webpage(self, query: str, limit: int) -> List[Track]:
        request = Request(
            f"https://search.bilibili.com/all?keyword={quote(query)}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                text = response.read().decode("utf-8", "ignore")
        except Exception:
            return []
        tracks: List[Track] = []
        seen: set[str] = set()
        for match in self._RESULT_PATTERN.finditer(text):
            bvid = match.group("bvid")
            if not bvid or bvid in seen:
                continue
            seen.add(bvid)
            title = self._decode_js_string(match.group("title"))
            title = html.unescape(title).replace('<em class="keyword">', "").replace("</em>", "")
            author = clean_artist_name(self._decode_js_string(match.group("author")))
            duration = duration_to_seconds(self._decode_js_string(match.group("duration")) or "")
            thumbnail = self._normalize_thumbnail_url(self._decode_js_string(match.group("pic")))
            tracks.append(Track(
                id=bvid, title=title, artist=author, source=self.source_name,
                page_url=f"https://www.bilibili.com/video/{bvid}",
                duration_sec=duration, thumbnail_url=thumbnail,
            ))
            if len(tracks) >= limit:
                break
        return tracks

    def _search_api(self, query: str, limit: int) -> List[Track]:
        per_page = 20
        pages = max(1, (limit + per_page - 1) // per_page)
        tracks: List[Track] = []
        for page in range(1, pages + 1):
            url = f"https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={quote(query)}&page={page}"
            response = run_subprocess(
                ["curl", "-sL", url,
                 "-H", "User-Agent: Mozilla/5.0",
                 "-H", "Referer: https://www.bilibili.com",
                 "-H", "Origin: https://www.bilibili.com"],
                timeout=30,
            )
            if response.returncode != 0 or not response.stdout.strip():
                continue
            try:
                payload = json.loads(response.stdout)
            except json.JSONDecodeError:
                continue
            if payload.get("code") not in (None, 0):
                continue
            for item in payload.get("data", {}).get("result", []):
                bvid = item.get("bvid")
                if not bvid:
                    continue
                title = html.unescape(item.get("title", ""))
                title = title.replace('<em class="keyword">', "").replace("</em>", "")
                tracks.append(Track(
                    id=bvid, title=title,
                    artist=clean_artist_name(item.get("author") or ""),
                    source=self.source_name,
                    page_url=f"https://www.bilibili.com/video/{bvid}",
                    duration_sec=duration_to_seconds(item.get("duration") or ""),
                    thumbnail_url=item.get("pic"),
                ))
                if len(tracks) >= limit:
                    return tracks
        return tracks

    def _decode_js_string(self, value: str) -> str:
        if not value:
            return ""
        try:
            return json.loads(f'"{value}"')
        except json.JSONDecodeError:
            return value

    def _normalize_thumbnail_url(self, value: str) -> str:
        if not value:
            return ""
        if value.startswith("//"):
            return f"https:{value}"
        return value

    def resolve_stream(self, track: Track) -> str:
        base_command = get_yt_dlp_command()
        if not base_command:
            raise RuntimeError("yt-dlp unavailable")
        command = base_command + [
            "-f", "bestaudio/best", "--no-playlist", "-J", track.page_url,
        ]
        result = run_subprocess(command, timeout=45)
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(result.stderr.strip() or "bilibili resolve failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError("bilibili resolve failed: invalid JSON")
        formats = payload.get("formats") or []
        audio_formats = [item for item in formats if item.get("url") and item.get("vcodec") == "none"]
        best = audio_formats[-1] if audio_formats else {}
        stream_url = best.get("url") or payload.get("url")
        if not stream_url:
            raise RuntimeError("no playable bilibili stream")
        track.duration_sec = payload.get("duration") or track.duration_sec
        track.thumbnail_url = payload.get("thumbnail") or track.thumbnail_url
        track.artist = clean_artist_name(payload.get("uploader") or track.artist)
        track.title = payload.get("title") or track.title
        return stream_url