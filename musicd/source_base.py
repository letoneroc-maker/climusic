from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from shared.models import Track


class SourceAdapter(ABC):
    source_name = "unknown"

    @abstractmethod
    def search(self, query: str, limit: int) -> List[Track]:
        raise NotImplementedError

    @abstractmethod
    def resolve_stream(self, track: Track) -> str:
        raise NotImplementedError