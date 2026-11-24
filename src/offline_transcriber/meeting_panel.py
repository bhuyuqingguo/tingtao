from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .meeting import marker_text
from .mini_recorder import RecordingMiniWindow


class MeetingNotesPanel(QFrame):
    """Encrypted-with-library meeting topic, time markers and audio recall."""

    status_changed = Signal(str)
    restore_requested = Signal()

    def __init__(self, library, recorder, player, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumHeight(208)
        self.library = library
        self.recorder = recorder
        self.player = player
        self.item_id: str | None = None
        self.markers: list[dict] = []
        self.elapsed = 0.0
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(7)
        title_row = QHBoxLayout()
        title = QLabel("会中速记与打点")
        title.setObjectName("cardTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("muted")
        title_row.addWidget(self.count_label)
        root.addLayout(title_row)
        meeting_row = QHBoxLayout()
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("会议主题／访谈题目，随音频一起保存")
        self.topic.setMaxLength(120)
        meeting_row.addWidget(self.topic, 1)
        self.mini_button = QPushButton("悬浮小窗")
        self.mini_button.setObjectName("smallButton")
        self.mini_button.setEnabled(False)
        self.mini_button.clicked.connect(self.show_mini)
        meeting_row.addWidget(self.mini_button)
        root.addLayout(meeting_row)
        marker_row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(("重点", "决定", "待办", "疑问"))
        self.kind.setMaximumWidth(86)
        marker_row.addWidget(self.kind)
        self.note = QLineEdit()
        self.note.setPlaceholderText("备注可留空；录音时记录当前时间，回放时添加到播放位置")
        self.note.setMaxLength(300)
        self.note.returnPressed.connect(self.add_marker)
        marker_row.addWidget(self.note, 1)
        self.add_button = QPushButton("◆ 打点  Ctrl+M")
        self.add_button.setObjectName("secondaryButton")
        self.add_button.clicked.connect(self.add_marker)
        marker_row.addWidget(self.add_button)
        root.addLayout(marker_row)
        self.marker_list = QListWidget()
        self.marker_list.setMaximumHeight(85)
        self.marker_list.setToolTip("双击回到该段原音复核")
        self.marker_list.itemDoubleClicked.connect(self.seek_marker)
        root.addWidget(self.marker_list)
        action_row = QHBoxLayout()
        hint = QLabel("会中打点 · 会后可双击回听 · 与音频一并加密")
        hint.setObjectName("muted")
        action_row.addWidget(hint, 1)
        save = QPushButton("保存速记")
        save.setObjectName("smallButton")
        save.clicked.connect(self.save)
        action_row.addWidget(save)
        export = QPushButton("导出打点")
        export.setObjectName("smallButton")
        export.clicked.connect(self.export)
        action_row.addWidget(export)
        remove = QPushButton("删除所选")
        remove.setObjectName("smallButton")
        remove.clicked.connect(self.remove_marker)
        action_row.addWidget(remove)
        root.addLayout(action_row)
        self.mini = RecordingMiniWindow()
        self.mini.marker_requested.connect(self.add_marker)
        self.mini.restore_requested.connect(self.restore_requested)

    def new_recording(self) -> None:
        self.item_id = None
        self.markers = []
        self.elapsed = 0.0
        if not self.topic.text().strip():
            self.topic.setText("未命名会议")
        self._refresh_markers()

    def update_elapsed(self, seconds: float) -> None:
        self.elapsed = seconds
        self.mini.update_state(seconds, self.topic.text())

    def recording_state(self, recording: bool) -> None:
        self.mini_button.setEnabled(recording)
        if recording:
            self.new_recording()
        else:
            self.mini.hide()

    def show_mini(self) -> None:
        if not self.recorder.recording:
            return
        self.mini.update_state(self.elapsed, self.topic.text())
        self.mini.show()
        self.mini.raise_()
        self.mini.activateWindow()
        self.status_changed.emit("已打开置顶速记小窗 · 关闭小窗不会停止录音")

    def set_item(self, item_id: str | None) -> None:
        if self.recorder.recording:
            return
        self._loading = True
        self.item_id = item_id
        entry = next((item for item in self.library.items() if item["id"] == item_id), None) if item_id else None
        self.topic.setText(entry.get("meeting_topic", "") if entry else "")
        self.markers = list(entry.get("markers", [])) if entry else []
        self._refresh_markers()
        self._loading = False

    def add_marker(self) -> None:
        if len(self.markers) >= 100:
            self.status_changed.emit("单次录音最多保存 100 条打点")
            return
        seconds = self.elapsed if self.recorder.recording else self.player.position() / 1000
        self.markers.append({"seconds": seconds, "type": self.kind.currentText(), "note": self.note.text().strip()})
        self.note.clear()
        self._refresh_markers()
        self.save()
        self.status_changed.emit("已记录时间点 · 双击打点可回到原音")

    def remove_marker(self) -> None:
        row = self.marker_list.currentRow()
        if 0 <= row < len(self.markers):
            del self.markers[row]
            self._refresh_markers()
            self.save()

    def _refresh_markers(self) -> None:
        self.marker_list.clear()
        for marker in self.markers:
            item = QListWidgetItem(marker_text(marker))
            self.marker_list.addItem(item)
        self.count_label.setText(f"{len(self.markers)} 条")

    def seek_marker(self, item: QListWidgetItem) -> None:
        row = self.marker_list.row(item)
        if not self.item_id or not (0 <= row < len(self.markers)):
            self.status_changed.emit("录音保存后，即可从打点回到原音")
            return
        try:
            source = self.library.materialize(self.item_id)
            self.player.setSource(QUrl.fromLocalFile(str(source)))
            self.player.setPosition(round(self.markers[row]["seconds"] * 1000))
            self.player.play()
            self.status_changed.emit("已从打点位置播放原音")
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "无法回听", str(exc))

    def attach_recording(self, item_id: str) -> None:
        self.item_id = item_id
        self.save()

    def save(self) -> None:
        if self._loading or not self.item_id:
            return
        try:
            self.library.set_meeting(self.item_id, self.topic.text(), self.markers)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "速记未保存", str(exc))

    def export(self) -> None:
        if not self.item_id:
            QMessageBox.information(self, "尚未收存", "请先保存录音或选择库内音频，再导出打点。")
            return
        self.save()
        entry = next(item for item in self.library.items() if item["id"] == self.item_id)
        filename, _ = QFileDialog.getSaveFileName(self, "导出会中打点", str(Path.home() / f"{entry['name']}_打点.md"), "Markdown 文件 (*.md)")
        if filename:
            Path(filename).write_text(self.library.meeting_markdown(self.item_id), encoding="utf-8-sig")
            self.status_changed.emit(f"会中打点已导出：{filename}")

    def shutdown(self) -> None:
        self.save()
        self.mini.close()
