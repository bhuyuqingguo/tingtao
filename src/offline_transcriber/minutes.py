from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .meeting import marker_text
from .record_naming import suggest_name_from_text

ACTION_WORDS = re.compile(r"待办|跟进|落实|负责|完成|提交|确认|对接|整理|准备|下发|反馈|下周|月底|之前|尽快|需要|应当|应该|将于|计划")
DECISION_WORDS = re.compile(r"决定|确定|同意|通过|结论|一致认为|定为|采用|不再|批准|明确")
STOP_WORDS = set("的了呢吧吗啊是我们你们他们这个那个就是然后所以如果因为已经还是一个没有可以需要以及进行对于通过关于现在觉得可能应该".split())


def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"【[^】]+】", "", text)
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", cleaned)
    result = []
    for part in parts:
        part = re.sub(r"\s+", " ", part).strip(" \t-—")
        if len(part) >= 4 and not part.isdigit() and "-->" not in part:
            result.append(part)
    return result


def _keywords(sentences: list[str]) -> Counter:
    words = Counter()
    for sentence in sentences:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]{2,6}", sentence.lower()):
            if word not in STOP_WORDS and not word.isdigit():
                words[word] += 1
    return words


def generate_minutes(result: Any, text: str | None = None, meeting_notes: list[dict] | None = None) -> str:
    body = text if text is not None else result.text
    sentences = _sentences(body)
    title = suggest_name_from_text(body) or "会议"
    if len(title) > 30:
        title = title[:30].rstrip("，。；、 ")
    speakers = []
    for segment in result.segments:
        speaker = getattr(segment, "speaker", None)
        if speaker and speaker != "未知说话人" and speaker not in speakers:
            speakers.append(speaker)
    keywords = _keywords(sentences)
    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (
            sum(keywords[word] for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]{2,6}", item[1].lower()))
            / max(8, len(item[1])) + (0.35 if DECISION_WORDS.search(item[1]) else 0) + (0.25 if ACTION_WORDS.search(item[1]) else 0),
            -item[0],
        ),
        reverse=True,
    )
    selected = sorted(index for index, _sentence in ranked[:min(8, max(3, len(sentences) // 5))])
    key_points = [sentences[index] for index in selected]
    decisions = [sentence for sentence in sentences if DECISION_WORDS.search(sentence)]
    actions = [sentence for sentence in sentences if ACTION_WORDS.search(sentence)]
    sources = [Path(source).name for source in (result.sources or (result.source,))]
    lines = [
        f"# {title}纪要", "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 来源：{'、'.join(sources)}",
        f"- 音频时长：{result.duration / 60:.1f} 分钟",
        f"- 识别参会人：{'、'.join(speakers) if speakers else '未开启或未可靠识别'}",
        "", "## 一、重点内容", "",
    ]
    lines.extend(f"{index}. {sentence}" for index, sentence in enumerate(key_points or sentences[:5], start=1))
    lines.extend(["", "## 二、决定事项", ""])
    lines.extend(f"- {sentence}" for sentence in decisions) if decisions else lines.append("- 未从文稿中检测到明确决定事项，请人工复核。")
    lines.extend(["", "## 三、待办与跟进", ""])
    lines.extend(f"- [ ] {sentence}" for sentence in actions) if actions else lines.append("- 未从文稿中检测到明确待办，请人工补充责任人与期限。")
    lines.extend([
        "", "## 四、会中打点", "",
    ])
    marked = False
    for note in meeting_notes or []:
        for marker in note.get("markers", []):
            lines.append(f"- {Path(note.get('source', '录音')).name} · {marker_text(marker)}")
            marked = True
    if not marked:
        lines.append("- 本次没有关联的会中打点；可在录音页为主题、重点、决定、待办或疑问打点。")
    lines.extend([
        "", "## 五、高频主题词", "",
        "、".join(word for word, _count in keywords.most_common(12)) or "无",
        "", "---", "本纪要由本地规则从转录文稿自动整理，未使用在线服务或生成式大模型；请结合原文复核事实、责任人和期限。",
    ])
    return "\n".join(lines) + "\n"
