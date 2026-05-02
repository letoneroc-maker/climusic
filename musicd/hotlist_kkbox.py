from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import List

from shared.lang import LANGS


class KKBoxHotChart:
    base_url = "https://kma.kkbox.com/charts/api/v1"

    def _current_chart_date(self) -> str:
        return datetime.now().date().isoformat()

    def _fetch_json(self, path: str, query: dict) -> dict:
        request = Request(f"{self.base_url}{path}?{urlencode(query)}", headers={"User-Agent": "music-agent/0.1"})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_categories(self) -> list:
        payload = self._fetch_json("/daily/categories", {"terr": "tw", "lang": "tc", "type": "song"})
        return payload.get("data", [])

    def get_hot_tracks(self, lang_key: str, limit: int) -> List[dict]:
        category_id = LANGS[lang_key]["kkbox_category_id"]
        base_date = datetime.now().date()
        for offset in range(8):
            check_date = (base_date - timedelta(days=offset)).isoformat()
            payload = self._fetch_json("/daily", {"terr": "tw", "lang": "tc", "type": "song", "category": category_id, "date": check_date, "limit": limit})
            songs = payload.get("data", {}).get("charts", {}).get("song") or []
            if songs:
                return songs[:limit]
        return []