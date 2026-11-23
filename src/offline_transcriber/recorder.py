from __future__ import annotations

import wave
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices


class AudioRecorder(QObject):
    elapsed_changed = Signal(float)
    level_changed = Signal(float)
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
        self.poll = QTimer(self)
        self.poll.setInterval(200)
        self.poll.timeout.connect(self._poll)

    @staticmethod
    def devices() -> list:
        return list(QMediaDevices.audioInputs())

    @staticmethod
    def default_device():
        return QMediaDevices.defaultAudioInput()

    @property
    def recording(self) -> bool:
        return self.source is not None

    def start(self, device, target: str | Path) -> None:
        if self.recording:
            raise RuntimeError("录音已经开始")
        if device is None or device.isNull():
            raise RuntimeError("没有可用的声音输入设备，请检查麦克风连接和系统权限")
        audio_format = QAudioFormat()
        audio_format.setSampleRate(16000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            raise RuntimeError("该音源不支持单声道 16 位录音，请更换输入设备")
        self.target = Path(target)
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.wav = wave.open(str(self.target), "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(16000)
        self.source = QAudioSource(device, audio_format, self)
        self._stopping = False
        self.timer.start()
        self.stream = self.source.start()
        if self.stream is None:
            self._cleanup()
            raise RuntimeError("音源无法启动，可能正被其他应用占用")
        self.stream.readyRead.connect(self._write_available)
        self.poll.start()
        self.state_changed.emit(True)

    def _write_available(self) -> None:
        if not self.stream or not self.wav:
            return
        data = self.stream.readAll()
        raw = bytes(data)
        if raw:
            self.wav.writeframesraw(raw)
            peak = 0
            for index in range(0, len(raw) - 1, 2):
                peak = max(peak, abs(int.from_bytes(raw[index:index + 2], "little", signed=True)))
            self.level_changed.emit(min(1.0, peak / 32768.0))

    def _poll(self) -> None:
        if self.recording:
            self.elapsed_changed.emit(self.timer.elapsed() / 1000.0)
            fatal_errors = (QAudio.Error.OpenError, QAudio.Error.IOError, QAudio.Error.FatalError)
            if self.source and self.source.error() in fatal_errors and not self._stopping:
                message = "录音设备发生错误，请检查连接后重试"
                self.cancel()
                self.failed.emit(message)

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
        self._cleanup()
        self.state_changed.emit(False)
        if target:
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
        self.level_changed.emit(0.0)
