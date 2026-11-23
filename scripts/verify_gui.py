"""Render real Qt widgets for visual regression checks; no transcription runs."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QMessageBox

from offline_transcriber.main_window import MainWindow
from offline_transcriber.splash import OceanSplash


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build-cache" / "gui-1.6.0"
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication([])
window = MainWindow()
window.resize(1260, 880)
window.show()
window._set_source(str(ROOT / "assets" / "test-zh.wav"))
app.processEvents()
assert window.tabs.maximumWidth() == 760
assert window.model_combo.count() == 2
assert "轻量模型" in window.model_combo.itemText(0)
assert window.audio_preset_combo.currentData() == "original"
for index, name in ((0, "workspace.png"), (1, "recording.png"), (3, "system.png")):
    window._show_page(index)
    if index == 1:
        window.audio_panel.waveform.set_values([abs(math.sin(i / 4)) * 0.72 for i in range(80)])
        window.audio_panel.level.set_level(0.42)
        window._set_recording_tally(True)
    app.processEvents()
    assert window.grab().save(str(OUT / name))
window._set_recording_tally(False)

# Real secondary widgets, rather than a mock drawing of their intended style.
dialog = QInputDialog(window)
dialog.setWindowTitle("启用音频库加密")
dialog.setLabelText("设置至少 8 个字符的密码：")
dialog.setTextValue("password")
dialog.resize(440, 170)
dialog.show()
app.processEvents()
assert dialog.palette().color(dialog.backgroundRole()).lightness() > 200
for label in dialog.findChildren(QLabel):
    if label.text():
        assert label.palette().color(label.foregroundRole()).lightness() < 130, label.text()
assert dialog.grab().save(str(OUT / "encryption-dialog.png"))
dialog.close()

message = QMessageBox(window)
message.setWindowTitle("录音已保存")
message.setText("是否现在加入离线转录队列？")
message.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
message.show()
app.processEvents()
assert message.grab().save(str(OUT / "message-dialog.png"))
message.close()

splash = OceanSplash(ROOT / "assets" / "guanhai-tingtao-logo-256.png", duration_ms=10000)
splash.show()
app.processEvents()
assert splash.grab().save(str(OUT / "splash.png"))
splash.sound.stop()
splash.finish()
window._update_launch_pending = True
window.close()
print(f"GUI previews and dialog contrast checks saved: {OUT}")
