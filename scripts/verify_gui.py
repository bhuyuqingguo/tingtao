"""Render real Qt widgets for visual regression checks; no transcription runs."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QMessageBox

from offline_transcriber.main_window import MainWindow
from offline_transcriber.splash import OceanSplash
from offline_transcriber.update_dialog import UpdateConfirmationDialog


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build-cache" / "gui-1.6.4"
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
        history = [abs(math.sin(i / 29)) * (0.18 + 0.58 * abs(math.sin(i / 173))) for i in range(1200)]
        window.audio_panel.waveform.set_values(history)
        assert window.audio_panel.waveform._values.maxlen == 1200
        assert len(window.audio_panel.waveform._values) == 1200
        assert window.audio_panel.limiter_check.isChecked()
        assert not window.audio_panel.gain_check.isChecked()
        assert window.audio_panel.denoise_combo.currentData() == "off"
        window.audio_panel.level.set_level(0.42)
        window._set_recording_tally(True)
        assert window.logo_tally._recording and window.logo_tally.timer.isActive()
        window.logo_tally._phase = math.pi / 2  # Capture the cinnabar-red phase.
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

update_dialog = UpdateConfirmationDialog({
    "from_version": "1.6.3", "to_version": "1.6.4", "package_kind": "application",
    "distribution_path": str(ROOT / "dist" / "TingTao-1.6.3-to-1.6.4-Windows-x64-Incremental.zip"),
    "total_payload_bytes": 12 * 1024 * 1024, "files": [{}, {}, {}, {}],
    "release_notes": "直接选择增量 ZIP，无需解压或处理 manifest。\n发行说明清晰展示，确认后一键升级并自动重启。\n个人配置、音频库、转录记录和模型保持不变。",
}, window)
update_dialog.show()
app.processEvents()
assert update_dialog.palette().color(update_dialog.backgroundRole()).lightness() > 200
assert update_dialog.grab().save(str(OUT / "update-dialog.png"))
update_dialog.close()

for scene_index in range(4):
    splash = OceanSplash(ROOT / "assets" / "guanhai-tingtao-logo-256.png", duration_ms=10000, scene_index=scene_index)
    splash.show()
    app.processEvents()
    assert splash.grab().save(str(OUT / f"splash-{scene_index + 1}-{splash.scene_name}.png"))
    splash.sound.stop()
    splash.finish()
random_splashes = [OceanSplash(ROOT / "assets" / "guanhai-tingtao-logo-256.png", duration_ms=10000).scene_index for _ in range(24)]
assert len(set(random_splashes)) > 1
window._update_launch_pending = True
window.close()
print(f"GUI previews and dialog contrast checks saved: {OUT}")
