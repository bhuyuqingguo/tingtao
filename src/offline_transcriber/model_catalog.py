from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import APP_ROOT


@dataclass(frozen=True)
class ModelSpec:
    key: str
    title: str
    directory_name: str
    description: str


MODEL_SPECS = {
    "small": ModelSpec("small", "small · 快速均衡", "faster-whisper-small", "速度优先，适合日常转录"),
    "medium": ModelSpec("medium", "medium · 更高精度", "faster-whisper-medium", "模型更大，识别更细致，耗时和内存更高"),
}
DEFAULT_MODEL = "small"
REQUIRED_MODEL_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")


def normalize_model_name(value: str | None) -> str:
    name = str(value or DEFAULT_MODEL).strip().lower()
    if name not in MODEL_SPECS:
        raise ValueError(f"不支持的识别模型：{value}；可选 small 或 medium")
    return name


def model_directory(value: str | None) -> Path:
    return APP_ROOT / "models" / MODEL_SPECS[normalize_model_name(value)].directory_name


def model_is_complete(value: str | None) -> bool:
    directory = model_directory(value)
    return all((directory / name).is_file() and (directory / name).stat().st_size > 0 for name in REQUIRED_MODEL_FILES)


def model_binary_size(value: str | None) -> int:
    path = model_directory(value) / "model.bin"
    return path.stat().st_size if path.is_file() else 0
