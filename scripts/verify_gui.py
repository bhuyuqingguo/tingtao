"""Render real Qt widgets for visual regression checks; no transcription runs."""
from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QTextDocument
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QMessageBox

from offline_transcriber.main_window import MainWindow
from offline_transcriber.splash import OceanSplash
from offline_transcriber.update_dialog import UpdateConfirmationDialog


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build-cache" / "gui-1.6.8"
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
window.hotwords_edit.setText("观海听涛，麒麟，观海听涛")
assert window._current_config().hotwords == "观海听涛，麒麟"
assert window.library_hotwords_button.isEnabled()
assert (ROOT / "core" / "guanhai-core.exe").is_file()
assert window.audio_panel.bafen.executable.name == "guanhai-core.exe"
assert any(button.text() == "导出八分包" for button in window.audio_panel.findChildren(type(window.audio_panel.encrypt_button)))

# Meeting markers survive the same encrypted library index and enter local minutes.
from offline_transcriber.audio_library import AudioLibrary
from offline_transcriber.minutes import generate_minutes
from offline_transcriber.transcriber import SegmentData, TranscriptionResult
with tempfile.TemporaryDirectory() as directory:
    meeting_library = AudioLibrary(Path(directory) / "vault")
    item = meeting_library.add(ROOT / "assets" / "test-zh.wav", "项目评审")
    meeting = window.audio_panel.meeting_panel
    original_library = meeting.library
    meeting.library = meeting_library
    meeting.topic.setText("季度项目评审")
    meeting.set_item(item["id"])
    meeting.note.setText("先验收短音频")
    meeting.kind.setCurrentText("决定")
    meeting.add_marker()
    assert meeting.marker_list.count() == 1
    assert "先验收短音频" in meeting_library.meeting_markdown(item["id"])
    notes = meeting_library.meeting_for_source(meeting_library.materialize(item["id"]))
    result = TranscriptionResult(
        source=str(meeting_library.materialize(item["id"])), model="small", language="zh",
        language_probability=1, duration=8, segments=(SegmentData(0, 4, "确定下周提交方案。"),), created_at="now",
    )
    assert notes and "先验收短音频" in generate_minutes(result, meeting_notes=[notes])
    meeting.marker_list.setCurrentRow(0)
    meeting.remove_marker()
    assert not meeting_library.items()[0]["markers"]
    meeting.library = original_library
    meeting.item_id = None
    meeting.topic.clear()
    meeting._refresh_markers()

# The compact always-on-top window is a meeting controller, not a recorder owner.
meeting = window.audio_panel.meeting_panel
meeting.recorder.poll.stop()  # Do not mix the preview timer with this UI-only fixture.
meeting.recorder._active_recording = True  # Real microphone capture is tested separately.
meeting.mini_button.setEnabled(True)
meeting.topic.setText("季度项目评审")
meeting.update_elapsed(65)
meeting.show_mini()
app.processEvents()
assert meeting.mini.isVisible()
assert "01:05" in meeting.mini.timer.text(), meeting.mini.timer.text()
meeting.mini.close()
app.processEvents()
assert not meeting.mini.isVisible()
assert meeting.recorder.recording
meeting.recorder._active_recording = False

# Review edits, full-text filters and speaker filters work on actual widgets.
result = TranscriptionResult(
    source="meeting.wav", model="small", language="zh", language_probability=1,
    duration=65, created_at="now", sources=("meeting.wav",),
    segments=(SegmentData(0, 4, "第一句", speaker="甲"), SegmentData(61, 65, "第二句", speaker="乙")),
)
window.review_panel.set_result(result)
window.review_panel.search.setText("第二")
assert window.review_panel.table.isRowHidden(0)
assert not window.review_panel.table.isRowHidden(1)
window.review_panel.search.clear()
window.review_panel.table.item(1, 2).setText("第二句已校订")
assert window.result.segments[1].text == "第二句已校订"
window.review_panel.speaker_filter.setCurrentIndex(window.review_panel.speaker_filter.findData("甲"))
assert not window.review_panel.table.isRowHidden(0)
assert window.review_panel.table.isRowHidden(1)
window.review_panel.clear()

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
    if index == 1:
        waveform = window.audio_panel.waveform
        level = window.audio_panel.level
        assert waveform.geometry().bottom() < level.geometry().top(), (waveform.geometry(), level.geometry())
        assert waveform.height() >= 118 and level.height() >= 66
    assert window.grab().save(str(OUT / name))
window._set_recording_tally(False)

# Exercise real chapter navigation, search, local media decoding and playback controls.
window._show_page(4)
tutorial = window.tutorial_panel
assert len(window.nav_buttons) == 5
assert tutorial.chapter_list.count() == 12
assert "第一次转录" in tutorial.content.toPlainText()
assert not tutorial.player.source().isEmpty()
deadline = time.monotonic() + 10
while tutorial.player.duration() <= 0 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.02)
assert tutorial.player.duration() > 20_000, tutorial.narration_status.text()
tutorial.toggle_playback()
deadline = time.monotonic() + 5
while tutorial.player.position() < 250 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.02)
assert tutorial.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
assert tutorial.player.position() >= 200
tutorial.toggle_playback()
assert tutorial.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
tutorial.search.setText("加密")
visible = [row for row in range(12) if not tutorial.chapter_list.item(row).isHidden()]
assert visible and len(visible) < 12
tutorial.search.clear()
tutorial.chapter_list.setCurrentRow(0)
tutorial.next_button.click()
assert tutorial.chapter_list.currentRow() == 1
tutorial.chapter_list.setCurrentRow(0)
app.processEvents()
for key in ("diagram", "screenshot"):
    url = QUrl.fromLocalFile(str(ROOT / tutorial.chapters[0][key]))
    resource = tutorial.content.document().resource(QTextDocument.ResourceType.ImageResource, url)
    assert not resource.isNull(), f"Tutorial image did not load: {url}"
assert tutorial.grab().save(str(OUT / "tutorial.png"))
tutorial.content.verticalScrollBar().setValue(390)
app.processEvents()
assert tutorial.grab().save(str(OUT / "tutorial-interface.png"))
tutorial.content.verticalScrollBar().setValue(0)
def capture_zoom():
    zoom = app.activeModalWidget()
    assert zoom is not None
    assert zoom.grab().save(str(OUT / "tutorial-image-zoom.png"))
    zoom.close()
QTimer.singleShot(250, capture_zoom)
tutorial._show_image(QUrl.fromLocalFile(str(ROOT / tutorial.chapters[0]["diagram"])))
assert app.activeModalWidget() is None
window._show_page(0)
assert tutorial.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState

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
    "from_version": "1.6.7", "to_version": "1.6.8", "package_kind": "application",
    "distribution_path": str(ROOT / "dist" / "TingTao-1.6.7-to-1.6.8-Windows-x64-Incremental.zip"),
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
