from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices

from .stream_audio import DENOISE_LEVELS, StreamingAudioProcessor


class AudioRecorder(QObject):
    elapsed_changed = Signal(float)
    level_changed = Signal(float)
    waveform_changed = Signal(float)
    state_changed = Signal(bool)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source: QAudioSource | None = None
        self.stream = None
        self.wav = None
        self.target: Path | None = None
        self.timer = QElapsedTimer()
        self._stopping = False
        self._active_recording = False
        self.limiter_enabled = True
        self.automatic_gain = False
        self.denoise = "off"
        self.processor = StreamingAudioProcessor()
        self.poll = QTimer(self)
        self.poll.setInterval(50)
        self.poll.timeout.connect(self._poll)

    @staticmethod
    def devices() -> list:
        return list(QMediaDevices.audioInputs())

    @staticmethod
    def default_device():
        return QMediaDevices.defaultAudioInput()

    @property
    def recording(self) -> bool:
        return self._active_recording

    def _format(self):
        audio_format = QAudioFormat()
        audio_format.setSampleRate(16000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        return audio_format

    def _open_source(self, device) -> None:
        if device is None or device.isNull():
            raise RuntimeError("没有可用的声音输入设备，请检查麦克风连接和系统权限")
        audio_format = self._format()
        if not device.isFormatSupported(audio_format):
            raise RuntimeError("该音源不支持单声道 16 位录音，请更换输入设备")
        self._cleanup()
        self.source = QAudioSource(device, audio_format, self)
        self.stream = self.source.start()
        if self.stream is None:
            self._cleanup()
            raise RuntimeError("音源无法启动，可能正被其他应用占用")
        self.stream.readyRead.connect(self._write_available)
        self.poll.start()

    def preview(self, device) -> None:
        """Monitor processed input without playing microphone audio to speakers."""
        if self.recording:
            return
        self._open_source(device)

    def stop_preview(self) -> None:
        if not self.recording:
            self._cleanup()

    def set_limiter(self, enabled: bool) -> None:
        self.limiter_enabled = bool(enabled)

    def set_automatic_gain(self, enabled: bool) -> None:
        self.automatic_gain = bool(enabled)

    def set_denoise(self, level: str) -> None:
        if level not in DENOISE_LEVELS:
            raise ValueError("未知降噪档位")
        self.denoise = level

    def start(self, device, target: str | Path) -> None:
        if self.recording:
            raise RuntimeError("录音已经开始")
        self.target = Path(target)
        self.target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._open_source(device)
            self.wav = wave.open(str(self.target), "wb")
            self.wav.setnchannels(1)
            self.wav.setsampwidth(2)
            self.wav.setframerate(16000)
        except Exception:
            self._cleanup()
            self.target.unlink(missing_ok=True)
            raise
        self._active_recording = True
        self._stopping = False
        self.timer.start()
        self.state_changed.emit(True)

    @staticmethod
    def _waveform(samples: np.ndarray, points: int = 80) -> list[float]:
        if samples.size == 0:
            return [0.0] * points
        edges = np.linspace(0, samples.size, points + 1, dtype=int)
        values = []
        for start, end in zip(edges[:-1], edges[1:]):
            values.append(0.0 if end <= start else float(np.max(np.abs(samples[start:end]))) / 32768.0)
        return values

    def _write_available(self) -> None:
        if not self.stream:
            return
        raw = bytes(self.stream.readAll())
        if not raw:
            return
        samples = np.frombuffer(raw, dtype="<i2").copy()
        samples = self.processor.process(
            samples, limiter=self.limiter_enabled, automatic_gain=self.automatic_gain, denoise=self.denoise,
        )
        if self.wav and samples.size:
            self.wav.writeframesraw(samples.tobytes())
        if samples.size:
            peak = float(np.max(np.abs(samples.astype(np.int32)))) / 32768.0
            self.level_changed.emit(min(1.0, peak))
            self.waveform_changed.emit(peak)

    def _poll(self) -> None:
        if self.recording:
            self.elapsed_changed.emit(self.timer.elapsed() / 1000.0)
        fatal_errors = (QAudio.Error.OpenError, QAudio.Error.IOError, QAudio.Error.FatalError)
        if self.source and self.source.error() in fatal_errors and not self._stopping:
            was_recording = self.recording
            self.cancel()
            if was_recording:
                self.failed.emit("录音设备发生错误，请检查连接后重试")

    def stop(self) -> Path | None:
        if not self.recording:
            return None
        self._stopping = True
        self._write_available()
        target = self.target
        self._cleanup()
        self.state_changed.emit(False)
        if target and target.is_file() and target.stat().st_size > 44:
            self.finished.emit(str(target))
        else:
            if target:
                target.unlink(missing_ok=True)
            self.failed.emit("没有录到声音，请检查输入设备")
        return target

    def cancel(self) -> None:
        target = self.target
        was_recording = self.recording
        self._cleanup()
        if was_recording:
            self.state_changed.emit(False)
        if was_recording and target:
            target.unlink(missing_ok=True)

    def _cleanup(self) -> None:
        self.poll.stop()
        if self.source:
            self.source.stop()
            self.source.deleteLater()
        if self.wav:
            self.wav.close()
        self.source = None
        self.stream = None
        self.wav = None
        self._active_recording = False
        self.processor.reset()
        self.level_changed.emit(0.0)
