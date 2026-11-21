from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
EXPLICIT_NAME = re.compile(r"^\s*(?:文件\s*名|标题|题目|会议\s*名称)\s*[：:]\s*(.+?)\s*$")
LEADING_MARKUP = re.compile(r"^\s*(?:【[^】]*(?:来源|说话人|未知)[^】]*】|\[[^\]]*(?:speaker|unknown)[^\]]*\])\s*", re.I)
TIMESTAMP = re.compile(r"^\s*(?:\d+\s*[.、)]\s*)?(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[,.]\d{1,3})?\s*(?:-->\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[,.]\d{1,3})?)?\s*")


def sanitize_record_name(value: str, max_length: int = 60) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .，。；;、")
    if len(value) > max_length:
        value = value[:max_length].rstrip(" .，。；;、")
    if value.upper() in WINDOWS_RESERVED:
        value = f"记录_{value}"
    if not value or set(value) <= {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ":", "-", "–"}:
        return ""
    return value


def suggest_name_from_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\ufeff", "").splitlines() if line.strip()]
    for line in lines[:30]:
        match = EXPLICIT_NAME.match(line)
        if match:
            name = sanitize_record_name(match.group(1))
            if name:
                return name
    for line in lines[:30]:
        if line.upper() in {"WEBVTT", "NOTE"} or line.isdigit() or line == "批次汇总":
            continue
        candidate = TIMESTAMP.sub("", line)
        previous = None
        while candidate != previous:
            previous = candidate
            candidate = LEADING_MARKUP.sub("", candidate).strip()
        candidate = re.sub(r"^(?:\d+\s*[.、)]\s*)", "", candidate)
        name = sanitize_record_name(candidate)
        if name:
            return name
    return ""


def read_record_text(folder: Path) -> str:
    folder = Path(folder)
    preferred = list(folder.glob("合并文稿.txt")) + list(folder.glob("批次汇总.txt")) + list(folder.glob("*.txt"))
    if preferred:
        return preferred[0].read_text(encoding="utf-8-sig")
    for path in folder.glob("*.json"):
        if path.name == "batch-report.json":
            continue
        try:
            return str(json.loads(path.read_text(encoding="utf-8-sig")).get("text", ""))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return ""


def rename_record(folder: str | Path, new_name: str) -> Path:
    folder = Path(folder).resolve()
    name = sanitize_record_name(new_name, max_length=80)
    if not folder.is_dir():
        raise ValueError("转录记录目录不存在")
    if not name:
        raise ValueError("无法从文稿中提取有效名称，请手动输入")
    destination = folder.with_name(name)
    if destination == folder:
        return folder
    if destination.exists():
        raise FileExistsError(f"已存在同名记录：{name}")
    old_stem = folder.name
    renames: list[tuple[Path, Path]] = []
    for suffix in (".txt", ".srt", ".vtt", ".json"):
        source = folder / f"{old_stem}{suffix}"
        if source.is_file():
            renames.append((source, folder / f"{name}{suffix}"))
    temporary_folder = folder.with_name(f".{folder.name}.{uuid.uuid4().hex}.renaming")
    completed: list[tuple[Path, Path]] = []
    try:
        os.replace(folder, temporary_folder)
        completed.append((folder, temporary_folder))
        for source, target in renames:
            source = temporary_folder / source.name
            target = temporary_folder / target.name
            os.replace(source, target)
            completed.append((source, target))
        os.replace(temporary_folder, destination)
        completed.append((temporary_folder, destination))
    except OSError:
        for source, target in reversed(completed[:-1]):
            if target.exists() and not source.exists():
                os.replace(target, source)
        raise
    return destination
