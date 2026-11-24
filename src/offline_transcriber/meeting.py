from __future__ import annotations

import re
from typing import Any


MARKER_TYPES = {"重点", "决定", "待办", "疑问"}
MAX_MARKERS = 100
MAX_NOTE_LENGTH = 300


def clock_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def clean_markers(markers: Any) -> list[dict]:
    if markers is None:
        return []
    if not isinstance(markers, list) or len(markers) > MAX_MARKERS:
        raise ValueError(f"打点记录须为不超过 {MAX_MARKERS} 条的列表")
    cleaned = []
    for marker in markers:
        if not isinstance(marker, dict):
            raise ValueError("打点记录结构无效")
        try:
            seconds = float(marker.get("seconds", -1))
        except (TypeError, ValueError) as exc:
            raise ValueError("打点时间无效") from exc
        if not 0 <= seconds <= 604800:
            raise ValueError("打点时间超出有效范围")
        kind = str(marker.get("type", "重点"))
        if kind not in MARKER_TYPES:
            raise ValueError("未知打点类型")
        note = " ".join(str(marker.get("note", "")).split())[:MAX_NOTE_LENGTH]
        cleaned.append({"seconds": seconds, "type": kind, "note": note})
    return sorted(cleaned, key=lambda item: item["seconds"])


def marker_text(marker: dict) -> str:
    note = str(marker.get("note", "")).strip()
    suffix = f" · {note}" if note else ""
    return f"{clock_time(float(marker['seconds']))}  【{marker.get('type', '重点')}】{suffix}"


def normalize_hotwords(value: str, limit: int = 30) -> str:
    words = []
    for word in re.split(r"[,，、;；\n]+", value):
        word = " ".join(word.split()).strip()
        if not word or len(word) > 40:
            continue
        if word.casefold() not in {item.casefold() for item in words}:
            words.append(word)
    return "，".join(words[:limit])


def polish_transcript(text: str) -> str:
    """Conservative offline cleanup; does not rewrite facts or generate content."""
    fillers = r"(?:嗯+|啊+|呃+|额+|这个嘛|那个嘛)"
    lines = []
    for original in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(rf"(?<![\w]){fillers}(?![\w])", "", original)
        line = re.sub(rf"(^|[，。！？；、：\s]){fillers}(?=$|[，。！？；、：\s])", r"\1", line)
        line = re.sub(r"([，。！？；、])\1+", r"\1", line)
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        line = re.sub(r"^[,，、；;]+", "", line)
        line = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", line)
        if line:
            lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")
