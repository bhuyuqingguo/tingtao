from __future__ import annotations

import os
import sys
from pathlib import Path


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


APP_ROOT = application_root()
DATA_ROOT = Path(os.environ.get("LOCAL_TRANSCRIBER_DATA", APP_ROOT / "data"))
MODEL_ROOT = APP_ROOT / "models" / "faster-whisper-small"
VOICEPRINT_MODEL_ROOT = APP_ROOT / "models" / "wespeaker-cnceleb-resnet34-LM"
FFMPEG_ROOT = APP_ROOT / "ffmpeg"
CONFIG_PATH = APP_ROOT / "config.json"
OUTPUT_ROOT = DATA_ROOT / "output"
TEMP_ROOT = DATA_ROOT / "temp"
LOG_ROOT = DATA_ROOT / "logs"
VOICEPRINT_LIBRARY_PATH = DATA_ROOT / "voiceprints.json"


def ensure_data_directories() -> None:
    for path in (OUTPUT_ROOT, TEMP_ROOT, LOG_ROOT):
        path.mkdir(parents=True, exist_ok=True)
