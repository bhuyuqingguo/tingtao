"""Repeatable local A/B/C comparison; clean synthetic speech is not a noise benchmark."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from offline_transcriber.audio_processing import AUDIO_PRESETS
from offline_transcriber.transcriber import OfflineTranscriber


ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "assets" / "test-zh.wav"
transcriber = OfflineTranscriber(model_name="small")
report = {"source": source.name, "sample_limit": "清晰合成中文样本；不代表真实噪声场景的普遍收益", "presets": {}}
for preset in AUDIO_PRESETS:
    started = time.perf_counter()
    audio, _duration = transcriber._decode(source, lambda _message: None, preset)
    decode_seconds = time.perf_counter() - started
    started = time.perf_counter()
    result = transcriber.transcribe(source, language="zh", audio_preset=preset)
    elapsed = time.perf_counter() - started
    report["presets"][preset] = {
        "text": result.text,
        "segments": len(result.segments),
        "decode_seconds": round(decode_seconds, 3),
        "transcribe_seconds_including_decode": round(elapsed, 3),
        "decoded_peak": round(float(np.max(np.abs(audio))), 5),
        "decoded_rms": round(float(np.sqrt(np.mean(audio ** 2))), 5),
    }
    print(preset, result.text, f"{elapsed:.2f}s", flush=True)
output = ROOT / "build-cache" / "audio-preset-evaluation.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(output)
