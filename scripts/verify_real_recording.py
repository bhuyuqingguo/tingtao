"""Record a short real input sample, inspect it, then delete it."""
from __future__ import annotations

import wave
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from offline_transcriber.main_window import MainWindow


ROOT = Path(__file__).resolve().parents[1]
target = ROOT / "build-cache" / "real-input-smoke.wav"
app = QApplication([])
window = MainWindow()
window._show_page(1)
window.show()
panel = window.audio_panel
panel.recorder.finished.disconnect()
outcome = {"failed": False}


def fail(message: str) -> None:
    outcome["failed"] = True
    print(message)
    app.exit(1)


def capture() -> None:
    assert panel.recorder.recording
    assert window.windowTitle().startswith("● 录音中")
    assert window.recording_border.isVisible()
    assert panel.limiter_check.isChecked()
    assert panel.gain_check.isChecked()
    assert panel.denoise_combo.currentData() == "high"
    assert len(panel.waveform._values) > 0
    window.grab().save(str(ROOT / "build-cache" / "gui-1.6.4" / "real-recording.png"))
    panel.recorder.stop()


def exercise_controls() -> None:
    panel.gain_check.setChecked(True)
    panel.denoise_combo.setCurrentIndex(panel.denoise_combo.findData("low"))
    QTimer.singleShot(350, lambda: panel.denoise_combo.setCurrentIndex(panel.denoise_combo.findData("medium")))
    QTimer.singleShot(700, lambda: panel.denoise_combo.setCurrentIndex(panel.denoise_combo.findData("high")))


def finished(filename: str) -> None:
    path = Path(filename)
    with wave.open(str(path), "rb") as audio:
        assert audio.getframerate() == 16000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getnframes() > 8000
        print(f"Real input recording passed: {audio.getnframes()} frames")
    path.unlink(missing_ok=True)
    app.quit()


panel.recorder.finished.connect(finished)
panel.recorder.failed.connect(fail)
try:
    panel.recorder.start(panel.device_combo.currentData(), target)
except RuntimeError as exc:
    fail(str(exc))
else:
    exercise_controls()
    QTimer.singleShot(1300, capture)
    QTimer.singleShot(10000, lambda: fail("Recording smoke test timed out"))
    code = app.exec()
    window._update_launch_pending = True
    window.close()
    target.unlink(missing_ok=True)
    raise SystemExit(code)
