from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .formatters import export_all
from .meeting import clock_time


class TranscriptReviewPanel(QWidget):
    """Timestamp-aware transcript proofreading against local source audio."""

    result_edited = Signal(object, str)
    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.result_directory: Path | None = None
        self._loading = False
        self._current_source = ""
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.output.setVolume(0.85)
        self.player.setAudioOutput(self.output)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(lambda value: self.progress.setRange(0, value))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("在正文中查找……")
        self.search.textChanged.connect(self._filter)
        toolbar.addWidget(self.search, 1)
        self.speaker_filter = QComboBox()
        self.speaker_filter.addItem("全部讲话人", "")
        self.speaker_filter.currentIndexChanged.connect(self._filter)
        toolbar.addWidget(self.speaker_filter)
        self.save_button = QPushButton("保存校订")
        self.save_button.setObjectName("secondaryButton")
        self.save_button.clicked.connect(self.save)
        toolbar.addWidget(self.save_button)
        root.addLayout(toolbar)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(("时间", "讲话人", "正文（可直接修改）"))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellClicked.connect(self._seek_row)
        self.table.itemChanged.connect(self._edit_cell)
        root.addWidget(self.table, 1)
        playback = QHBoxLayout()
        self.play_button = QPushButton("▶ 播放本段")
        self.play_button.setObjectName("secondaryButton")
        self.play_button.clicked.connect(self.toggle_playback)
        playback.addWidget(self.play_button)
        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.sliderMoved.connect(self.player.setPosition)
        playback.addWidget(self.progress, 1)
        self.time_label = QLabel("00:00:00")
        playback.addWidget(self.time_label)
        root.addLayout(playback)
        self.source_label = QLabel("选择一行，从对应时间点播放原音；修改不会重写原始音频。")
        self.source_label.setObjectName("muted")
        self.source_label.setWordWrap(True)
        root.addWidget(self.source_label)

    def set_result(self, result, directory: str | Path | None = None) -> None:
        self.clear()
        self.result = result
        self.result_directory = Path(directory) if directory else None
        if result is None:
            return
        self._loading = True
        self.table.setRowCount(len(result.segments))
        speakers = []
        for row, segment in enumerate(result.segments):
            values = (clock_time(segment.start), segment.speaker or "—", segment.text.strip())
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column < 2:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
            if segment.speaker and segment.speaker not in speakers:
                speakers.append(segment.speaker)
        self.speaker_filter.clear()
        self.speaker_filter.addItem("全部讲话人", "")
        for speaker in speakers:
            self.speaker_filter.addItem(speaker, speaker)
        self._loading = False
        if result.segments:
            self.table.selectRow(0)
        self.source_label.setText("点击任意行，从该句时间点播放；编辑正文后点击“保存校订”写回 TXT、JSON 和字幕。")

    def clear(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self._current_source = ""
        self._loading = True
        self.table.setRowCount(0)
        self.search.clear()
        self.speaker_filter.clear()
        self.speaker_filter.addItem("全部讲话人", "")
        self.result = None
        self.result_directory = None
        self._loading = False
        self.play_button.setText("▶ 播放本段")
        self.time_label.setText("00:00:00")
        self.progress.setValue(0)

    def _filter(self) -> None:
        query = self.search.text().strip().casefold()
        speaker = str(self.speaker_filter.currentData() or "")
        for row in range(self.table.rowCount()):
            text = self.table.item(row, 2).text().casefold()
            name = self.table.item(row, 1).text()
            self.table.setRowHidden(row, bool(query and query not in text) or bool(speaker and speaker != name))

    def _seek_row(self, row: int, _column: int = 0) -> None:
        if not self.result or not (0 <= row < len(self.result.segments)):
            return
        segment = self.result.segments[row]
        source = segment.source or (self.result.sources[0] if self.result.sources else self.result.source)
        if not source or not Path(source).is_file():
            self.status_changed.emit(f"原音不在原位置：{source or '未知文件'}，可继续校订文本")
            return
        if source != self._current_source:
            self.player.setSource(QUrl.fromLocalFile(source))
            self._current_source = source
        seconds = segment.start
        if self.result.batch_mode == "merged":
            seconds = getattr(segment, "source_start", None)
            if seconds is None:
                self.status_changed.emit("旧版合并文稿不含单文件内时间，暂不能精确跳转；单文件与队列记录不受影响")
                return
        self.player.setPosition(max(0, round(seconds * 1000)))
        self.source_label.setText(f"原音：{Path(source).name} · {clock_time(seconds)}")
        self.status_changed.emit(f"已定位到 {clock_time(seconds)} · 可播放核对原音")

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            row = self.table.currentRow()
            if self.player.source().isEmpty() and row >= 0:
                self._seek_row(row)
            self.player.play()

    def _position_changed(self, milliseconds: int) -> None:
        self.progress.blockSignals(True)
        self.progress.setValue(milliseconds)
        self.progress.blockSignals(False)
        self.time_label.setText(clock_time(milliseconds / 1000))
        self.play_button.setText("Ⅱ 暂停" if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState else "▶ 播放本段")
        if not self.result or not self._current_source or self.table.state() == QAbstractItemView.State.EditingState:
            return
        seconds = milliseconds / 1000
        candidates = []
        for index, segment in enumerate(self.result.segments):
            start = getattr(segment, "source_start", None)
            start = segment.start if start is None else start
            if ((segment.source or self.result.source) == self._current_source
                    and start <= seconds < start + (segment.end - segment.start)
                    and not self.table.isRowHidden(index)):
                candidates.append(index)
        if candidates:
            self.table.selectRow(candidates[-1])

    def _edit_cell(self, item: QTableWidgetItem) -> None:
        if self._loading or not self.result or item.column() != 2 or not (0 <= item.row() < len(self.result.segments)):
            return
        text = item.text().strip()
        if not text:
            self._loading = True
            item.setText(self.result.segments[item.row()].text)
            self._loading = False
            self.status_changed.emit("空白句段未保存，请保留文字或在外部文稿中处理")
            return
        row = item.row()
        self.result = replace(
            self.result,
            segments=tuple(replace(segment, text=text) if index == row else segment for index, segment in enumerate(self.result.segments)),
        )
        self.result_edited.emit(self.result, self.result.text)

    def save(self) -> None:
        if not self.result:
            return
        if not self.result_directory:
            self.result_edited.emit(self.result, self.result.text)
            self.status_changed.emit("校订已应用到当前结果，请使用下方按钮导出保存")
            return
        stem = "合并文稿" if self.result.batch_mode == "merged" else "批次汇总"
        export_all(self.result, self.result_directory, stem, self.result.text)
        self.result_edited.emit(self.result, self.result.text)
        self.status_changed.emit(f"校订已保存到 {self.result_directory.name} · 原音未修改")

    def shutdown(self) -> None:
        self.player.stop()
