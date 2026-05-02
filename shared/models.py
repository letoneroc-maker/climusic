from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional
from uuid import uuid4


@dataclass
class Track:
    id: str
    title: str
    artist: str
    source: str
    page_url: str
    stream_url: Optional[str] = None
    duration_sec: Optional[int] = None
    thumbnail_url: Optional[str] = None
    rank_score: float = 0.0
    resolved_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["Track"]:
        if data is None:
            return None
        return cls(**data)


@dataclass
class Queue:
    queue_id: str = field(default_factory=lambda: str(uuid4()))
    mode: str = "loop"
    source_type: str = "keyword"
    source_query: str = ""
    items: List[Track] = field(default_factory=list)
    current_index: Optional[int] = None
    total: int = 0
    lang: str = "mandarin"
    source_preference: str = "youtube"

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        return payload

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["Queue"]:
        if data is None:
            return None
        items = [Track.from_dict(item) for item in data.get("items", [])]
        return cls(
            queue_id=data.get("queue_id", str(uuid4())),
            mode=data.get("mode", "loop"),
            source_type=data.get("source_type", "keyword"),
            source_query=data.get("source_query", ""),
            items=[item for item in items if item is not None],
            current_index=data.get("current_index"),
            total=data.get("total", len(items)),
            lang=data.get("lang", "mandarin"),
            source_preference=data.get("source_preference", "youtube"),
        )


@dataclass
class PlaybackState:
    state: str = "idle"
    current_track: Optional[Track] = None
    queue: Optional[Queue] = None
    volume: int = 50
    muted: bool = False
    last_nonzero_volume: int = 50
    lang_preference: str = "mandarin"
    source_preference: str = "youtube"
    error_code: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "current_track": self.current_track.to_dict() if self.current_track else None,
            "queue": self.queue.to_dict() if self.queue else None,
            "volume": self.volume,
            "muted": self.muted,
            "last_nonzero_volume": self.last_nonzero_volume,
            "lang_preference": self.lang_preference,
            "source_preference": self.source_preference,
            "error_code": self.error_code,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "PlaybackState":
        if not data:
            return cls()
        return cls(
            state=data.get("state", "idle"),
            current_track=Track.from_dict(data.get("current_track")),
            queue=Queue.from_dict(data.get("queue")),
            volume=data.get("volume", 50),
            muted=data.get("muted", False),
            last_nonzero_volume=data.get("last_nonzero_volume", 50),
            lang_preference=data.get("lang_preference", "mandarin"),
            source_preference=data.get("source_preference", "youtube"),
            error_code=data.get("error_code"),
            message=data.get("message"),
        )