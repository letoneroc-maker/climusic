from __future__ import annotations

from typing import Dict, Optional


LANGS: Dict[str, dict] = {
    "mandarin": {
        "display": "华语",
        "kkbox_category_id": 297,
        "kkbox_label": "華語",
        "aliases": {"华语", "中文", "汉语", "国语", "mandarin", "cn", "zh"},
    },
    "english": {
        "display": "英语",
        "kkbox_category_id": 390,
        "kkbox_label": "西洋",
        "aliases": {"英语", "英文", "西洋", "english", "en"},
    },
    "japanese": {
        "display": "日语",
        "kkbox_category_id": 308,
        "kkbox_label": "日語",
        "aliases": {"日语", "日文", "japanese", "jp", "ja"},
    },
    "korean": {
        "display": "韩语",
        "kkbox_category_id": 314,
        "kkbox_label": "韓語",
        "aliases": {"韩语", "韩文", "korean", "kr", "ko"},
    },
    "cantonese": {
        "display": "粤语",
        "kkbox_category_id": 320,
        "kkbox_label": "粵語",
        "aliases": {"粤语", "廣東話", "广东话", "cantonese", "yue", "hk"},
    },
}

DEFAULT_LANG = "mandarin"


def normalize_lang(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    candidate = value.strip().lower()
    if not candidate:
        return None
    for key, spec in LANGS.items():
        aliases = {alias.lower() for alias in spec["aliases"]}
        if candidate == key or candidate in aliases:
            return key
    return None


def display_lang(lang_key: str) -> str:
    return LANGS.get(lang_key, LANGS[DEFAULT_LANG])["display"]