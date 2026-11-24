from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .audio_processing import AUDIO_PRESETS
from .model_catalog import DEFAULT_MODEL, MODEL_SPECS
from .paths import CONFIG_PATH, OUTPUT_ROOT


@dataclass
class AppConfig:
    language: str = "zh"
    beam_size: int = 5
    vad_filter: bool = True
    output_directory: str = str(OUTPUT_ROOT)
    batch_mode: str = "queue"
    theme: str = "classical"
    model_name: str = DEFAULT_MODEL
    speaker_enabled: bool = False
    speaker_threshold: float = 0.55
    audio_preset: str = "original"
    hotwords: str = ""


class ConfigStore:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path

    def load(self) -> AppConfig:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            config = AppConfig()
            for key in asdict(config):
                if key in payload:
                    setattr(config, key, payload[key])
            config.beam_size = max(1, min(10, int(config.beam_size)))
            config.vad_filter = bool(config.vad_filter)
            config.speaker_enabled = bool(config.speaker_enabled)
            config.speaker_threshold = max(0.30, min(0.90, float(config.speaker_threshold)))
            if config.language not in {"auto", "zh", "en"}:
                config.language = "zh"
            if config.batch_mode not in {"queue", "merged"}:
                config.batch_mode = "queue"
            if config.theme not in {"classical", "modern"}:
                config.theme = "classical"
            if config.model_name not in MODEL_SPECS:
                config.model_name = DEFAULT_MODEL
            if config.audio_preset not in AUDIO_PRESETS:
                config.audio_preset = "original"
            return config
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        self.path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
