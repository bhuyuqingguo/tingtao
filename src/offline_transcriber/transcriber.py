from __future__ import annotations

import os

# These flags must be set before importing the inference stack.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["DO_NOT_TRACK"] = "1"

import json
import subprocess
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
from faster_whisper import WhisperModel

from .audio_processing import AUDIO_PRESETS, audio_filter
from .formatters import result_text
from .model_catalog import MODEL_SPECS, model_directory, model_is_complete, normalize_model_name
from .paths import FFMPEG_ROOT, TEMP_ROOT, ensure_data_directories


class TranscriptionCancelled(Exception):
    pass


@dataclass(frozen=True)
class SegmentData:
    start: float
    end: float
    text: str
    source: str | None = None
    source_index: int | None = None
    speaker: str | None = None
    speaker_similarity: float | None = None

    def to_dict(self) -> dict:
        payload = {"start": self.start, "end": self.end, "text": self.text}
        if self.source is not None:
            payload["source"] = self.source
            payload["source_index"] = self.source_index
        if self.speaker is not None:
            payload["speaker"] = self.speaker
            payload["speaker_similarity"] = self.speaker_similarity
        return payload


@dataclass(frozen=True)
class TranscriptionResult:
    source: str
    model: str
    language: str
    language_probability: float | None
    duration: float
    segments: tuple[SegmentData, ...]
    created_at: str
    sources: tuple[str, ...] = ()
    batch_mode: str = "single"
    speaker_embeddings: dict[str, list[float]] | None = None

    @property
    def text(self) -> str:
        return result_text(self)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "sources": list(self.sources) or [self.source],
            "batch_mode": self.batch_mode,
            "model": self.model,
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "created_at": self.created_at,
            "segments": [segment.to_dict() for segment in self.segments],
            "text": self.text,
        }


ProgressCallback = Callable[[int, str], None]
SegmentCallback = Callable[[SegmentData], None]
LogCallback = Callable[[str], None]


class OfflineTranscriber:
    def __init__(
        self, cancel_event: threading.Event | None = None, model_name: str = "small",
        speaker_enabled: bool = False, speaker_threshold: float = 0.55,
    ):
        self.cancel_event = cancel_event or threading.Event()
        self.model_name = normalize_model_name(model_name)
        self.model_root = model_directory(self.model_name)
        self.speaker_enabled = bool(speaker_enabled)
        self.speaker_threshold = float(speaker_threshold)
        self._model: WhisperModel | None = None

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise TranscriptionCancelled("任务已取消")

    @staticmethod
    def _creation_flags() -> int:
        return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    @staticmethod
    def _executable(name: str) -> str:
        return f"{name}.exe" if os.name == "nt" else name

    def _load_model(self, log: LogCallback) -> WhisperModel:
        if self._model is not None:
            return self._model
        if not model_is_complete(self.model_name):
            raise FileNotFoundError(f"本地 {self.model_name} 模型不完整：{self.model_root}")
        self._check_cancelled()
        log(f"正在从本地加载 {MODEL_SPECS[self.model_name].title}：{self.model_root}")
        threads = max(1, min(8, os.cpu_count() or 4))
        self._model = WhisperModel(
            str(self.model_root),
            device="cpu",
            compute_type="int8",
            cpu_threads=threads,
            local_files_only=True,
        )
        log(f"{self.model_name} 模型加载完成（CPU int8，{threads} 线程）")
        return self._model

    def _probe_duration(self, source: Path) -> float:
        ffprobe = FFMPEG_ROOT / self._executable("ffprobe")
        if not ffprobe.is_file():
            return 0.0
        command = [
            str(ffprobe), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(source),
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=30,
            creationflags=self._creation_flags(), check=False,
        )
        try:
            return max(0.0, float(completed.stdout.strip()))
        except (ValueError, TypeError):
            return 0.0

    def _decode(self, source: Path, log: LogCallback, audio_preset: str = "original") -> tuple[np.ndarray, float]:
        ffmpeg = FFMPEG_ROOT / self._executable("ffmpeg")
        if not ffmpeg.is_file():
            raise FileNotFoundError(f"部署包缺少 FFmpeg：{ffmpeg}")
        ensure_data_directories()
        temporary = TEMP_ROOT / f"decode-{uuid.uuid4().hex}.wav"
        filters = audio_filter(audio_preset)
        command = [
            str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(source), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
        ]
        if filters:
            command.extend(["-af", filters])
        command.extend(["-c:a", "pcm_s16le", "-f", "wav", "-y", str(temporary)])
        log(f"正在本地解码音频 · {AUDIO_PRESETS[audio_preset]['title']}")
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=self._creation_flags(),
        )
        try:
            while process.poll() is None:
                if self.cancel_event.is_set():
                    process.kill()
                    process.wait()
                    raise TranscriptionCancelled("任务已取消")
                time.sleep(0.1)
            stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
            if process.returncode != 0:
                raise RuntimeError(f"音频解码失败：{stderr.strip() or '无法读取音轨'}")
            with wave.open(str(temporary), "rb") as wav_file:
                frames = wav_file.readframes(wav_file.getnframes())
                duration = wav_file.getnframes() / float(wav_file.getframerate())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            return audio, duration
        finally:
            if process.stderr:
                process.stderr.close()
            temporary.unlink(missing_ok=True)

    def transcribe(
        self,
        source: str | Path,
        language: str = "zh",
        beam_size: int = 5,
        vad_filter: bool = True,
        audio_preset: str = "original",
        progress: ProgressCallback | None = None,
        on_segment: SegmentCallback | None = None,
        log: LogCallback | None = None,
    ) -> TranscriptionResult:
        source_path = Path(source).resolve()
        progress = progress or (lambda _value, _message: None)
        on_segment = on_segment or (lambda _segment: None)
        log = log or (lambda _message: None)
        if not source_path.is_file():
            raise FileNotFoundError(f"找不到输入文件：{source_path}")
        self._check_cancelled()
        model = self._load_model(log)
        duration = self._probe_duration(source_path)
        audio, decoded_duration = self._decode(source_path, log, audio_preset)
        duration = duration or decoded_duration
        if duration <= 0 or audio.size == 0:
            raise RuntimeError("音频为空或文件中没有可用音轨")
        self._check_cancelled()
        selected_language = None if language == "auto" else language
        progress(2, "正在识别语音")
        log("开始离线识别，不会访问网络")
        segments, info = model.transcribe(
            audio,
            task="transcribe",
            language=selected_language,
            beam_size=max(1, min(10, beam_size)),
            temperature=0.0,
            vad_filter=vad_filter,
            vad_parameters={"min_silence_duration_ms": 500} if vad_filter else None,
            condition_on_previous_text=True,
            word_timestamps=False,
        )
        collected: list[SegmentData] = []
        for item in segments:
            self._check_cancelled()
            segment = SegmentData(float(item.start), float(item.end), item.text)
            collected.append(segment)
            on_segment(segment)
            percentage = min(99, max(3, int(segment.end / duration * 100)))
            progress(percentage, f"已识别 {segment.end:.0f} / {duration:.0f} 秒")
        self._check_cancelled()
        speaker_embeddings = None
        if self.speaker_enabled and collected:
            from .speaker import SpeakerRecognizer
            log("正在本地分离说话人并匹配声纹库……")
            progress(99, "正在识别说话人")
            recognizer = SpeakerRecognizer(self.speaker_threshold)
            collected, speaker_embeddings = recognizer.annotate(audio, collected)
            log(f"说话人分离完成，共 {len(speaker_embeddings)} 个临时声纹")
        result = TranscriptionResult(
            source=str(source_path),
            model=f"faster-whisper-{self.model_name} (CPU int8)",
            language=info.language,
            language_probability=float(info.language_probability) if info.language_probability is not None else None,
            duration=float(duration),
            segments=tuple(collected),
            created_at=datetime.now(timezone.utc).astimezone().isoformat(),
            sources=(str(source_path),),
            speaker_embeddings=speaker_embeddings,
        )
        progress(100, "转录完成")
        log(f"识别完成，共 {len(collected)} 个片段")
        return result
