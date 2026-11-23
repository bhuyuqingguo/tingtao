from __future__ import annotations

import re

from PySide6.QtCore import QUrl, Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSlider, QTextBrowser, QVBoxLayout, QWidget,
)

from .paths import APP_ROOT
from .tutorial_content import TUTORIAL_CHAPTERS


class TutorialPanel(QWidget):
    """Detailed offline guide with per-chapter local narration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chapters = TUTORIAL_CHAPTERS
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.75)
        self._build()
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._media_error)
        self.chapter_list.setCurrentRow(0)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 18)
        root.setSpacing(12)
        title = QLabel("听涛学堂")
        title.setObjectName("pageTitle")
        subtitle = QLabel("从第一次转录到受控环境升级 · 详细图文与本地中文语音讲解")
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(14)
        navigation = QVBoxLayout()
        navigation.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索教学内容……")
        self.search.textChanged.connect(self._filter)
        navigation.addWidget(self.search)
        self.chapter_list = QListWidget()
        self.chapter_list.setObjectName("recordList")
        self.chapter_list.setMinimumWidth(240)
        self.chapter_list.setMaximumWidth(290)
        for item in self.chapters:
            entry = QListWidgetItem(f"{item['number']:02d}  {item['title']}\n　 {item['subtitle']}")
            entry.setToolTip(item["subtitle"])
            self.chapter_list.addItem(entry)
        self.chapter_list.currentRowChanged.connect(self.open_chapter)
        navigation.addWidget(self.chapter_list, 1)
        body.addLayout(navigation)

        content_column = QVBoxLayout()
        content_column.setSpacing(9)
        self.content = QTextBrowser()
        self.content.setObjectName("tutorialContent")
        self.content.setOpenExternalLinks(False)
        self.content.setReadOnly(True)
        content_column.addWidget(self.content, 1)

        player_card = QFrame()
        player_card.setObjectName("card")
        player_layout = QVBoxLayout(player_card)
        player_layout.setContentsMargins(14, 10, 14, 10)
        player_layout.setSpacing(7)
        narration_row = QHBoxLayout()
        self.play_button = QPushButton("▶ 播放本章讲解")
        self.play_button.setObjectName("primaryButton")
        self.play_button.clicked.connect(self.toggle_playback)
        narration_row.addWidget(self.play_button)
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("secondaryButton")
        self.stop_button.clicked.connect(self.stop)
        narration_row.addWidget(self.stop_button)
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(0, 0)
        self.position.sliderMoved.connect(self.player.setPosition)
        narration_row.addWidget(self.position, 1)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("muted")
        narration_row.addWidget(self.time_label)
        player_layout.addLayout(narration_row)
        options = QHBoxLayout()
        self.narration_status = QLabel("本地语音 · 不联网")
        self.narration_status.setObjectName("muted")
        options.addWidget(self.narration_status, 1)
        options.addWidget(QLabel("语速"))
        self.rate_combo = QComboBox()
        for label, rate in (("0.75×", 0.75), ("1.0×", 1.0), ("1.25×", 1.25), ("1.5×", 1.5)):
            self.rate_combo.addItem(label, rate)
        self.rate_combo.setCurrentIndex(1)
        self.rate_combo.currentIndexChanged.connect(lambda: self.player.setPlaybackRate(float(self.rate_combo.currentData())))
        options.addWidget(self.rate_combo)
        options.addWidget(QLabel("音量"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(75)
        self.volume.setMaximumWidth(110)
        self.volume.valueChanged.connect(lambda value: self.audio_output.setVolume(value / 100))
        options.addWidget(self.volume)
        player_layout.addLayout(options)
        content_column.addWidget(player_card)

        chapter_buttons = QHBoxLayout()
        self.previous_button = QPushButton("← 上一章")
        self.previous_button.setObjectName("ghostButton")
        self.previous_button.clicked.connect(lambda: self._step(-1))
        chapter_buttons.addWidget(self.previous_button)
        chapter_buttons.addStretch(1)
        self.next_button = QPushButton("下一章 →")
        self.next_button.setObjectName("secondaryButton")
        self.next_button.clicked.connect(lambda: self._step(1))
        chapter_buttons.addWidget(self.next_button)
        content_column.addLayout(chapter_buttons)
        body.addLayout(content_column, 1)
        root.addLayout(body, 1)

    def open_chapter(self, row: int) -> None:
        if not 0 <= row < len(self.chapters):
            return
        item = self.chapters[row]
        self.stop()
        self.content.setHtml(self._html(item))
        self.content.verticalScrollBar().setValue(0)
        path = APP_ROOT / item["audio"]
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.position.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        self.narration_status.setText(f"第 {item['number']} 章 · 本地中文讲解 · 不联网" if path.is_file() else "本章语音文件缺失，请检查程序完整性")
        self.play_button.setEnabled(path.is_file())
        self.stop_button.setEnabled(path.is_file())
        self.previous_button.setEnabled(row > 0)
        self.next_button.setEnabled(row < len(self.chapters) - 1)

    @staticmethod
    def _html(item: dict) -> str:
        return f"""<html><body style='font-family:Microsoft YaHei,sans-serif;color:#29474A;line-height:1.65'>
        <div style='color:#8B643E;font-size:13px'>第 {item['number']:02d} 章 · {item['title']} · {item['subtitle']}</div>
        {item['body']}
        <hr><p><b>本章讲解稿</b></p><p>{item['narration']}</p>
        </body></html>"""

    def _filter(self) -> None:
        query = self.search.text().strip().casefold()
        first_visible = -1
        for row, item in enumerate(self.chapters):
            searchable = re.sub(r"<[^>]+>", " ", item["title"] + item["subtitle"] + item["body"] + item["narration"]).casefold()
            hidden = bool(query) and query not in searchable
            self.chapter_list.item(row).setHidden(hidden)
            if not hidden and first_visible < 0:
                first_visible = row
        current = self.chapter_list.currentRow()
        if current < 0 or self.chapter_list.item(current).isHidden():
            self.chapter_list.setCurrentRow(first_visible)

    def _step(self, delta: int) -> None:
        row = self.chapter_list.currentRow() + delta
        if 0 <= row < len(self.chapters) and not self.chapter_list.item(row).isHidden():
            self.chapter_list.setCurrentRow(row)

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self) -> None:
        self.player.stop()

    def shutdown(self) -> None:
        self.stop()
        self.player.setSource(QUrl())

    def _position_changed(self, value: int) -> None:
        if not self.position.isSliderDown():
            self.position.setValue(value)
        self.time_label.setText(f"{self._time(value)} / {self._time(self.player.duration())}")

    def _duration_changed(self, value: int) -> None:
        self.position.setRange(0, value)
        self._position_changed(self.player.position())

    def _playback_state(self, state) -> None:
        self.play_button.setText("Ⅱ 暂停讲解" if state == QMediaPlayer.PlaybackState.PlayingState else "▶ 播放本章讲解")

    def _media_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)
            self.narration_status.setText("本章讲解播放完毕 · 可继续下一章")

    def _media_error(self, _error, message="") -> None:
        self.narration_status.setText(f"语音暂无法播放：{message or '请检查本地解码器'}")

    @staticmethod
    def _time(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
