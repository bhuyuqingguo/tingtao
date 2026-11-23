from __future__ import annotations


AUDIO_PRESETS = {
    "original": {
        "title": "原声 · 不做处理",
        "filter": "",
        "description": "完整保留原始音频，默认选择，适合清晰录音。",
    },
    "light": {
        "title": "轻度降噪 · 保留细节",
        "filter": "highpass=f=60,afftdn=nr=6:nf=-35,loudnorm=I=-20:TP=-2:LRA=11",
        "description": "轻微削减低频与平稳底噪，并统一响度；适合轻微环境噪声。",
    },
    "standard": {
        "title": "标准降噪 · 噪声较多",
        "filter": "highpass=f=70,lowpass=f=8000,afftdn=nr=12:nf=-30,loudnorm=I=-18:TP=-2:LRA=11",
        "description": "更积极削减底噪并统一响度；可能损失轻声、远场或音乐细节，建议与原声对照。",
    },
}


def audio_filter(preset: str) -> str:
    """Only allow a known local preset, never arbitrary FFmpeg filter text."""
    if preset not in AUDIO_PRESETS:
        raise ValueError(f"未知音频处理方式：{preset}")
    return AUDIO_PRESETS[preset]["filter"]
