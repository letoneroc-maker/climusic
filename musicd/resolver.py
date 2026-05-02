from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from typing import Dict, Iterable, List, Sequence, Tuple

from musicd.hotlist_kkbox import KKBoxHotChart
from musicd.source_bilibili import BilibiliAdapter
from musicd.source_soundcloud import SoundCloudAdapter
from musicd.source_youtube import YouTubeAdapter
from shared.errors import MusicError
from shared.models import Queue, Track
from shared.source import DEFAULT_SOURCE, normalize_source
from shared.utils import (
    clean_artist_name,
    matches_negative_term,
    normalize_title,
    query_tokens,
)


class Resolver:
    def __init__(self) -> None:
        self.adapters = {
            "youtube": YouTubeAdapter(),
            "bilibili": BilibiliAdapter(),
            "soundcloud": SoundCloudAdapter(),
        }
        self.hot_chart = KKBoxHotChart()
        self.platform_weight = {"youtube": 0.40, "bilibili": 0.20, "soundcloud": 0.10}

    def build_keyword_queue(self, query: str, lang_key: str = "mandarin", limit: int = 20, source_name: str = DEFAULT_SOURCE) -> Queue:
        source_key = normalize_source(source_name) or DEFAULT_SOURCE
        selected = self._search_keyword_tracks(query=query, limit=limit, source_names=(source_key,))
        if not selected:
            raise MusicError("NO_RESULTS", f"未找到与\"{query}\"相关的可播放歌曲")
        tracks = self._resolve_tracks(selected)
        if not tracks:
            raise MusicError("SOURCE_RESOLVE_FAILED", "音源解析失败，请稍后重试")
        return Queue(source_type="keyword", source_query=query, items=tracks, current_index=1, total=len(tracks), lang=lang_key, source_preference=source_key)

    def build_hot_queue(self, lang_key: str, limit: int = 20, source_name: str = DEFAULT_SOURCE) -> Queue:
        source_key = normalize_source(source_name) or DEFAULT_SOURCE
        hot_items = self.hot_chart.get_hot_tracks(lang_key, max(limit * 2, 40))
        selected: List[Track] = []
        for item in hot_items:
            artist = clean_artist_name(item.get("artist_name") or item.get("artist_roles") or "")
            title = item.get("song_name") or ""
            candidates = self._search_keyword_tracks(f"{artist} {title}".strip(), limit=1, source_names=(source_key,))
            if candidates:
                candidate = candidates[0]
                candidate.rank_score += 1.0 - (len(selected) * 0.01)
                selected.append(candidate)
            if len(selected) >= limit:
                break
        tracks = self._resolve_tracks(selected[:limit])
        if not tracks:
            raise MusicError("NO_RESULTS", "热门榜单暂时可用，但没有匹配到可播放音源")
        return Queue(source_type="hot", source_query=lang_key, items=tracks, current_index=1, total=len(tracks), lang=lang_key, source_preference=source_key)

    def refresh_stream(self, track: Track) -> Track:
        adapter = self.adapters[track.source]
        track.stream_url = adapter.resolve_stream(track)
        track.resolved_at = time.time()
        return track

    def _search_keyword_tracks(self, query: str, limit: int, source_names: Sequence[str] | None = None) -> List[Track]:
        all_candidates: List[Track] = []
        search_limit = max(limit * 2, 20)
        source_names = tuple(source_names or ("youtube", "bilibili", "soundcloud"))
        preserve_source_order = len(source_names) == 1
        with ThreadPoolExecutor(max_workers=len(source_names)) as executor:
            future_map = {executor.submit(self.adapters[source_name].search, query, search_limit): source_name for source_name in source_names}
            for future in as_completed(future_map):
                try:
                    raw_tracks = future.result() or []
                except Exception:
                    continue
                filtered = [track for track in raw_tracks if self._is_track_allowed(track)]
                if preserve_source_order:
                    all_candidates.extend(filtered)
                else:
                    scored = [self._score_track(track, query) for track in filtered]
                    all_candidates.extend(scored)
        deduped = self._dedupe(all_candidates)
        if preserve_source_order:
            return deduped[:limit]
        ranked = sorted(deduped, key=lambda item: item.rank_score, reverse=True)
        return ranked[:limit]

    def _resolve_tracks(self, tracks: Sequence[Track]) -> List[Track]:
        if not tracks:
            return []
        resolved_by_index: Dict[int, Track] = {}
        max_workers = min(6, len(tracks))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(self.refresh_stream, track): index for index, track in enumerate(tracks)}
            for future in as_completed(future_map):
                index = future_map[future]
                try:
                    resolved_by_index[index] = future.result()
                except Exception:
                    continue
        return [resolved_by_index[index] for index in sorted(resolved_by_index)]

    def _is_track_allowed(self, track: Track) -> bool:
        title = track.title or ""
        if matches_negative_term(title):
            return False
        if track.duration_sec is not None:
            if track.duration_sec < 30 or track.duration_sec > 900:
                return False
        normalized = normalize_title(title)
        if not normalized:
            return False
        return True

    def _score_track(self, track: Track, query: str) -> Track:
        raw_title = (track.title or "").lower()
        title = normalize_title(track.title)
        artist = normalize_title(track.artist)
        score = self.platform_weight.get(track.source, 0.0) + track.rank_score
        tokens = query_tokens(query)
        normalized_query = normalize_title(query)
        if track.source == "youtube" and "music.youtube.com/" in (track.page_url or ""):
            matched = sum(1 for token in tokens if token in title or token in artist)
            if tokens:
                score += 0.15 * (matched / len(tokens))
            if len(tokens) >= 2 and not any(token in title for token in tokens[1:]):
                score -= 0.8
            track.rank_score = round(score, 4)
            return track
        if title == normalized_query:
            score += 0.9
        elif normalized_query and normalized_query in title:
            score += 0.35
        matched = sum(1 for token in tokens if token in title or token in artist)
        if tokens:
            score += matched / len(tokens)
        title_matched = sum(1 for token in tokens if token in title)
        if tokens and title_matched == len(tokens):
            score += 0.2
        artist_matched = sum(1 for token in tokens if token in artist)
        if artist_matched:
            score += 0.45 * artist_matched
        elif len(tokens) >= 2:
            score -= 0.25
        first_token = normalize_title(tokens[0]) if tokens else ""
        last_token = normalize_title(tokens[-1]) if tokens else ""
        if first_token and artist == first_token:
            score += 0.9
        elif first_token and first_token in artist:
            score += 0.35
        elif len(tokens) >= 2:
            score -= 0.8
        if any(char.isdigit() for char in (track.artist or "")) and first_token and first_token not in artist:
            score -= 0.45
        if last_token and title == last_token:
            score += 1.0
        elif last_token and (title.startswith(last_token) or title.endswith(last_token)):
            score += 0.45
        elif len(tokens) >= 2:
            score -= 1.1
        if track.duration_sec is not None:
            if 120 <= track.duration_sec <= 360:
                score += 0.2
            elif 30 <= track.duration_sec < 120:
                score -= 0.1
            elif 360 < track.duration_sec <= 900:
                score -= 0.05
        bonus_terms = {"official": 0.28, "官方": 0.28, "原唱": 0.45, "official audio": 0.3, "music video": 0.18, "mv": 0.08}
        for term, bonus in bonus_terms.items():
            if term in raw_title or term in artist:
                score += bonus
        if " - " in (track.title or ""):
            prefix = normalize_title((track.title or "").split(" - ", 1)[0])
            if prefix and not any(token in prefix for token in tokens) and prefix not in artist:
                score -= 0.4
        penalty_terms = {"remix": 0.3, "cover": 0.35, "翻唱": 0.45, "ai": 0.35, "ai周杰伦": 0.7, "歌词": 0.12, "lyric": 0.12, "合集": 0.4, "串烧": 0.35, "纯享": 0.15, "伴奏": 0.4, "karaoke": 0.5, "instrumental": 0.55, "inst": 0.5, "纯音乐": 0.55, "新專輯": 0.25, "新专辑": 0.25, "片段": 0.25, "剪辑": 0.25, "dj": 0.2}
        for term, penalty in penalty_terms.items():
            if term in raw_title:
                score -= penalty
        track.rank_score = round(score, 4)
        return track

    def _dedupe(self, tracks: Iterable[Track]) -> List[Track]:
        result: List[Track] = []
        seen_exact: set = set()
        seen_fuzzy: Dict[Tuple[str, str], str] = {}
        for track in tracks:
            exact_key = (track.source, track.id)
            if exact_key in seen_exact:
                continue
            fuzzy_key = (normalize_title(track.title), normalize_title(track.artist))
            if fuzzy_key in seen_fuzzy and seen_fuzzy[fuzzy_key] == track.source:
                continue
            seen_exact.add(exact_key)
            seen_fuzzy[fuzzy_key] = track.source
            result.append(track)
        return result