from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from .batch import transcribe_batch
from .transcriber import OfflineTranscriber, TranscriptionCancelled


class TranscriptionWorker(QThread):
    progress_changed = Signal(int, str)
    segment_ready = Signal(object)
    log_ready = Signal(str)
    file_started = Signal(str, int, int)
    file_completed = Signal(object, int, int)
    file_failed = Signal(str, str, int, int)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self, sources: list[str], language: str, beam_size: int, vad_filter: bool, mode: str,
        model_name: str = "small", speaker_enabled: bool = False, speaker_threshold: float = 0.55,
        audio_preset: str = "original", hotwords: str = "", parent=None,
    ):
        super().__init__(parent)
        self.sources = list(sources)
        self.language = language
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.mode = mode
        self.model_name = model_name
        self.speaker_enabled = speaker_enabled
        self.speaker_threshold = speaker_threshold
        self.audio_preset = audio_preset
        self.hotwords = hotwords.strip()
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            transcriber = OfflineTranscriber(
                self.cancel_event, model_name=self.model_name,
                speaker_enabled=self.speaker_enabled, speaker_threshold=self.speaker_threshold,
            )
            summary = transcribe_batch(
                transcriber,
                self.sources,
                mode=self.mode,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
                audio_preset=self.audio_preset,
                hotwords=self.hotwords,
                progress=self.progress_changed.emit,
                on_segment=self.segment_ready.emit,
                log=self.log_ready.emit,
                file_started=self.file_started.emit,
                file_completed=self.file_completed.emit,
                file_failed=self.file_failed.emit,
            )
            self.succeeded.emit(summary)
        except TranscriptionCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
