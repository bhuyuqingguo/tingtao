from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _timestamp_parts(seconds: float) -> tuple[int, int, int, int]:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return hours, minutes, secs, milliseconds


def format_timestamp(seconds: float, vtt: bool = False) -> str:
    hours, minutes, secs, milliseconds = _timestamp_parts(seconds)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"


def _source_name(segment: Any) -> str:
    source = getattr(segment, "source", None)
    return Path(source).name if source else ""


def _segment_text(segments: tuple[Any, ...] | list[Any], index: int) -> str:
    segment = segments[index]
    text = segment.text.strip()
    speaker = getattr(segment, "speaker", None)
    if speaker:
        text = f"【{speaker}】{text}"
    source = _source_name(segment)
    if source and (index == 0 or _source_name(segments[index - 1]) != source):
        return f"【{source}】\n{text}"
    return text


def result_text(result: Any) -> str:
    segments = list(result.segments)
    return "\n".join(
        _segment_text(segments, index)
        for index, segment in enumerate(segments) if segment.text.strip()
    )


def to_srt(result: Any) -> str:
    segments = list(result.segments)
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}\n"
            f"{_segment_text(segments, index - 1)}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_vtt(result: Any) -> str:
    segments = list(result.segments)
    blocks = ["WEBVTT"]
    for index, segment in enumerate(segments):
        blocks.append(
            f"{format_timestamp(segment.start, vtt=True)} --> "
            f"{format_timestamp(segment.end, vtt=True)}\n{_segment_text(segments, index)}"
        )
    return "\n\n".join(blocks) + "\n"


def to_json(result: Any, edited_text: str | None = None) -> str:
    payload = result.to_dict()
    payload["text"] = result_text(result) if edited_text is None else edited_text
    return json.dumps(payload, ensure_ascii=False, indent=2)


def export_all(result: Any, directory: Path, stem: str, edited_text: str | None = None) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {
        directory / f"{stem}.txt": result_text(result) if edited_text is None else edited_text,
        directory / f"{stem}.srt": to_srt(result),
        directory / f"{stem}.vtt": to_vtt(result),
        directory / f"{stem}.json": to_json(result, edited_text),
    }
    for path, content in outputs.items():
        path.write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8-sig" if path.suffix == ".txt" else "utf-8")
    return list(outputs)
