from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

import os

from .audio_library import AudioLibrary, InvalidVaultPasswordError, VaultLockedError
from .bafen_core import BafenCore, BafenError
from .meeting_panel import MeetingNotesPanel
from .paths import APP_ROOT, DATA_ROOT
from .recorder import AudioRecorder
from .recording_widgets import LevelMeter, WaveformWidget


class AudioLibraryPanel(QWidget):
    transcribe_requested = Signal(list)
    status_changed = Signal(str)
    recording_changed = Signal(bool)

    def __init__(self, library: AudioLibrary | None = None, parent=None):
        super().__init__(parent)
        self.library = library or AudioLibrary()
        core_name = "guanhai-core.exe" if os.name == "nt" else "guanhai-core"
        self.bafen = BafenCore(APP_ROOT / "core" / core_name)
        self.recorder = AudioRecorder(self)
        self.recorder.elapsed_changed.connect(self._elapsed)
        self.recorder.state_changed.connect(self._recording_state)
        self.recorder.finished.connect(self._recording_finished)
        self.recorder.failed.connect(lambda message: QMessageBox.warning(self, "录音未完成", message))
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)
        self.source_chime = QSoundEffect(self)
        self.source_chime.setSource(QUrl.fromLocalFile(str(APP_ROOT / "assets" / "source-chime.wav")))
        self.source_chime.setVolume(0.55)
        self._busy = False
        self._build()
        self.recorder.level_changed.connect(self.level.set_level)
        self.recorder.waveform_changed.connect(self.waveform.append_peak)
        self.refresh_devices()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 18)
        root.setSpacing(10)
        title = QLabel("听涛录音馆")
        title.setObjectName("pageTitle")
        subtitle = QLabel("选择音源、命名收存、关键词管理；录音和库内音频都可直接离线转录。")
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        record_card = QFrame()
        # Keep the 60-second waveform and its meter separate at the minimum window size.
        record_card.setMinimumHeight(330)
        record_card.setObjectName("card")
        record_layout = QVBoxLayout(record_card)
        record_layout.setContentsMargins(16, 12, 16, 12)
        record_layout.setSpacing(9)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("输入音源"))
        self.device_combo = self._combo()
        self.device_combo.setMaximumWidth(460)
        self.device_combo.activated.connect(self._device_selected)
        source_row.addWidget(self.device_combo, 1)
        self.test_source_button = self._button("提示音", self._test_source, "smallButton")
        source_row.addWidget(self.test_source_button)
        self.refresh_devices_button = self._button("刷新", self.refresh_devices, "smallButton")
        source_row.addWidget(self.refresh_devices_button)
        self.record_button = self._button("● 开始录音", self._toggle_recording, "primaryButton")
        source_row.addWidget(self.record_button)
        record_layout.addLayout(source_row)
        self.waveform = WaveformWidget()
        record_layout.addWidget(self.waveform)
        self.level = LevelMeter()
        self.level.setMaximumWidth(10000)
        record_layout.addWidget(self.level)
        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)
        processing_label = QLabel("声音优化")
        processing_label.setObjectName("cardTitle")
        controls_row.addWidget(processing_label)
        self.limiter_check = QCheckBox("自动防爆音")
        self.limiter_check.setChecked(True)
        self.limiter_check.setToolTip("平滑限制突发峰值，减少数字削波；无法修复声卡输入端已经产生的失真")
        self.limiter_check.toggled.connect(self.recorder.set_limiter)
        controls_row.addWidget(self.limiter_check)
        self.gain_check = QCheckBox("自动增益")
        self.gain_check.setToolTip("缓慢提升偏弱声音并压低突增音量，避免频繁大幅起落")
        self.gain_check.toggled.connect(self.recorder.set_automatic_gain)
        controls_row.addWidget(self.gain_check)
        controls_row.addWidget(QLabel("降噪"))
        self.denoise_combo = self._combo()
        for label, value in (("关闭", "off"), ("低", "low"), ("中", "medium"), ("高", "high")):
            self.denoise_combo.addItem(label, value)
        self.denoise_combo.setToolTip("低：保留更多细节；中：日常环境；高：明显底噪。强降噪可能影响轻声和远场语音")
        self.denoise_combo.currentIndexChanged.connect(lambda: self.recorder.set_denoise(str(self.denoise_combo.currentData())))
        controls_row.addWidget(self.denoise_combo)
        controls_row.addStretch(1)
        record_layout.addLayout(controls_row)
        self.record_status = QLabel("历史波形与实时电平仅用于监听，不将麦克风回放到扬声器")
        self.record_status.setObjectName("muted")
        record_layout.addWidget(self.record_status)
        root.addWidget(record_card)

        self.meeting_panel = MeetingNotesPanel(self.library, self.recorder, self.player)
        self.meeting_panel.status_changed.connect(self.status_changed)
        root.addWidget(self.meeting_panel)

        security_row = QHBoxLayout()
        self.vault_status = QLabel()
        self.vault_status.setObjectName("muted")
        self.encrypt_button = self._button("", self._encryption_action, "secondaryButton")
        self.disable_encryption_button = self._button("关闭加密", self._disable_encryption, "ghostButton")
        security_row.addWidget(self.vault_status, 1)
        security_row.addWidget(self.disable_encryption_button)
        security_row.addWidget(self.encrypt_button)
        root.addLayout(security_row)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索音频名称、原始文件名或关键词……")
        self.search.textChanged.connect(self._filter)
        search_row.addWidget(self.search, 1)
        for text, handler in (("导入音频", self._import), ("重命名", self._rename), ("音频关键词", self._edit_keywords)):
            search_row.addWidget(self._button(text, handler, "secondaryButton"))
        root.addLayout(search_row)
        self.audio_list = QListWidget()
        self.audio_list.setMinimumHeight(108)
        self.audio_list.setObjectName("recordList")
        self.audio_list.itemSelectionChanged.connect(self._selection_changed)
        self.audio_list.itemDoubleClicked.connect(lambda _item: self._transcribe())
        root.addWidget(self.audio_list, 1)

        actions = QHBoxLayout()
        for text, handler, style in (
            ("加入转录队列", self._transcribe, "primaryButton"),
            ("播放／停止", self._play, "secondaryButton"),
            ("导出音频", self._export, "secondaryButton"),
            ("导出八分包", self._export_bafen, "secondaryButton"),
            ("删除", self._delete, "secondaryButton"),
        ):
            actions.addWidget(self._button(text, handler, style))
        actions.addStretch(1)
        root.addLayout(actions)

        keyword_card = QWidget()
        keyword_card.setMinimumHeight(145)
        keyword_card.setObjectName("card")
        keyword_layout = QVBoxLayout(keyword_card)
        keyword_title = QLabel("常用关键词库")
        keyword_title.setObjectName("cardTitle")
        keyword_layout.addWidget(keyword_title)
        keyword_row = QHBoxLayout()
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("输入需要长期保存的检索词，如项目名、地点、人物……")
        self.keyword_edit.returnPressed.connect(self._add_keyword)
        keyword_row.addWidget(self.keyword_edit, 1)
        keyword_row.addWidget(self._button("存储关键词", self._add_keyword, "secondaryButton"))
        keyword_row.addWidget(self._button("移除所选", self._remove_keyword, "smallButton"))
        keyword_layout.addLayout(keyword_row)
        self.keyword_list = QListWidget()
        self.keyword_list.setMaximumHeight(90)
        keyword_layout.addWidget(self.keyword_list)
        root.addWidget(keyword_card)

    @staticmethod
    def _combo():
        from PySide6.QtWidgets import QComboBox
        return QComboBox()

    @staticmethod
    def _button(text, handler, style) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(style)
        button.clicked.connect(handler)
        return button

    def refresh_devices(self) -> None:
        selected = self.device_combo.currentData()
        self.device_combo.clear()
        for device in self.recorder.devices():
            self.device_combo.addItem(device.description(), device)
        index = self.device_combo.findData(selected)
        self.device_combo.setCurrentIndex(max(0, index))
        if not self.device_combo.count():
            self.device_combo.addItem("未检测到输入设备", None)
        else:
            self._start_preview()

    def _start_preview(self) -> None:
        try:
            self.recorder.preview(self.device_combo.currentData())
            self.record_status.setText("音源已连接 · 左侧回看近 60 秒，电平条显示当前音量")
        except (OSError, RuntimeError) as exc:
            self.record_status.setText(f"音源暂不可用：{exc}")

    def _device_selected(self) -> None:
        self._start_preview()
        self.source_chime.play()

    def _test_source(self) -> None:
        self.source_chime.play()
        self.record_status.setText("已播放音源提示音 · 电平来自当前麦克风，不会回放麦克风")

    def _toggle_recording(self) -> None:
        if self.recorder.recording:
            self.recorder.stop()
            return
        target = DATA_ROOT / "recordings" / f"录音_{datetime.now():%Y%m%d_%H%M%S}.wav"
        try:
            self.recorder.start(self.device_combo.currentData(), target)
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "无法开始录音", str(exc))

    def _recording_state(self, recording: bool) -> None:
        self.meeting_panel.recording_state(recording)
        self.record_button.setText("■ 停止并保存" if recording else "● 开始录音")
        self.device_combo.setEnabled(not recording and not self._busy)
        self.refresh_devices_button.setEnabled(not recording and not self._busy)
        self.test_source_button.setEnabled(not recording and not self._busy)
        self.recording_changed.emit(recording)
        if recording:
            self.waveform.clear()
        else:
            self.level.set_level(0)
            self._start_preview()

    def _elapsed(self, seconds: float) -> None:
        self.meeting_panel.update_elapsed(seconds)
        minutes, seconds = divmod(int(seconds), 60)
        self.record_status.setText(f"正在录音 {minutes:02d}:{seconds:02d} · 点击“停止并保存”收存")

    def _recording_finished(self, filename: str) -> None:
        default = self.meeting_panel.topic.text().strip() or f"会议录音 {datetime.now():%m月%d日 %H时%M分}"
        name, accepted = QInputDialog.getText(self, "命名本次录音", "音频名称：", text=default)
        try:
            item = self.library.add(filename, name.strip() if accepted else default)
            self.meeting_panel.attach_recording(item["id"])
            Path(filename).unlink(missing_ok=True)
            self.record_status.setText(f"已收存：{item['name']}")
            self.refresh()
            self._select(item["id"])
            if self.library.unlocked and QMessageBox.question(self, "录音已保存", "是否现在加入离线转录队列？") == QMessageBox.StandardButton.Yes:
                self._transcribe()
        except (OSError, ValueError, VaultLockedError) as exc:
            QMessageBox.warning(self, "录音未收存", f"{exc}\n原始录音保留在：{filename}")

    def refresh(self) -> None:
        locked = not self.library.unlocked
        self.vault_status.setText("🔒 观海·八分保护中 · 解锁后才能浏览和转录" if locked else ("🔓 观海·八分 BFQ 已解锁 · 离开前建议锁定" if self.library.encryption_enabled else "本地音频库 · 当前未加密"))
        self.encrypt_button.setText("解锁音频库" if locked else ("锁定音频库" if self.library.encryption_enabled else "启用加密存储"))
        self.disable_encryption_button.setVisible(self.library.encryption_enabled and not locked)
        self.audio_list.clear()
        self.keyword_list.clear()
        if locked:
            item = QListWidgetItem("音频库已锁定。名称、关键词和音频内容均不可见。")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.audio_list.addItem(item)
            return
        try:
            for entry in self.library.items():
                size = entry.get("bytes", 0) / 1024 / 1024
                keywords = "、".join(entry.get("keywords", [])) or "未设关键词"
                protection = "🔒" if entry.get("encrypted") else "○"
                item = QListWidgetItem(f"{protection} {entry['name']}  ·  {size:.1f} MiB\n关键词：{keywords}")
                item.setData(Qt.ItemDataRole.UserRole, entry["id"])
                item.setToolTip(f"原始文件：{entry.get('original_name', '')}\n收存时间：{entry.get('created_at', '')}")
                self.audio_list.addItem(item)
            self.keyword_list.addItems(self.library.keywords())
            self._filter()
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "音频库读取失败", str(exc))

    def _filter(self) -> None:
        query = self.search.text().strip().casefold()
        for row in range(self.audio_list.count()):
            item = self.audio_list.item(row)
            item.setHidden(bool(query) and query not in (item.text() + item.toolTip()).casefold())

    def _selected_id(self) -> str | None:
        item = self.audio_list.currentItem()
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    def _select(self, item_id: str) -> None:
        for row in range(self.audio_list.count()):
            if self.audio_list.item(row).data(Qt.ItemDataRole.UserRole) == item_id:
                self.audio_list.setCurrentRow(row)
                return

    def _selection_changed(self) -> None:
        self.meeting_panel.save()
        self.player.stop()
        self.meeting_panel.set_item(self._selected_id())

    def _guard(self) -> bool:
        if not self.library.unlocked:
            QMessageBox.information(self, "音频库已锁定", "请先输入密码解锁。")
            return False
        if self.recorder.recording:
            QMessageBox.information(self, "正在录音", "请先停止并保存当前录音。")
            return False
        return True

    def _import(self) -> None:
        if not self._guard():
            return
        filenames, _ = QFileDialog.getOpenFileNames(self, "导入到音频库", "", "音视频文件 (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.wma *.mp4 *.mkv *.mov *.avi *.webm);;所有文件 (*)")
        if not filenames:
            return
        imported = []
        for filename in filenames:
            try:
                imported.append(self.library.add(filename))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "部分音频未导入", f"{Path(filename).name}：{exc}")
        self.refresh()
        if imported:
            self._select(imported[-1]["id"])
            self.status_changed.emit(f"已导入 {len(imported)} 个音频到本地音频库")

    def _rename(self) -> None:
        item_id = self._selected_id()
        if not item_id:
            return
        current = self.audio_list.currentItem().text().split("  ·  ", 1)[0].lstrip("🔒○ ")
        name, accepted = QInputDialog.getText(self, "重命名音频", "音频名称：", text=current)
        if accepted:
            try:
                self.library.rename(item_id, name)
                self.refresh()
                self._select(item_id)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "未重命名", str(exc))

    def _edit_keywords(self) -> None:
        item_id = self._selected_id()
        if not item_id:
            QMessageBox.information(self, "先选择音频", "请选择要设置关键词的音频。")
            return
        entry = next(item for item in self.library.items() if item["id"] == item_id)
        value, accepted = QInputDialog.getText(self, "音频关键词", "多个关键词用逗号分隔：", text="、".join(entry.get("keywords", [])))
        if accepted:
            words = value.replace("，", ",").replace("、", ",").split(",")
            self.library.set_keywords(item_id, words)
            self.refresh()
            self._select(item_id)

    def _add_keyword(self) -> None:
        if not self._guard():
            return
        try:
            self.library.add_keyword(self.keyword_edit.text())
            self.keyword_edit.clear()
            self.refresh()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "关键词未保存", str(exc))

    def _remove_keyword(self) -> None:
        item = self.keyword_list.currentItem()
        if item:
            self.library.remove_keyword(item.text())
            self.refresh()

    def _transcribe(self) -> None:
        if self._busy:
            return
        items = self.audio_list.selectedItems() or ([self.audio_list.currentItem()] if self.audio_list.currentItem() else [])
        paths = []
        try:
            for item in items:
                item_id = item.data(Qt.ItemDataRole.UserRole)
                if item_id:
                    paths.append(str(self.library.materialize(str(item_id))))
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "无法读取音频", str(exc))
            return
        if paths:
            self.transcribe_requested.emit(paths)

    def _play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.stop()
            return
        item_id = self._selected_id()
        if item_id:
            try:
                self.player.setSource(QUrl.fromLocalFile(str(self.library.materialize(item_id))))
                self.player.play()
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.warning(self, "无法播放", str(exc))

    def _export(self) -> None:
        item_id = self._selected_id()
        if not item_id:
            return
        entry = next(item for item in self.library.items() if item["id"] == item_id)
        filename, _ = QFileDialog.getSaveFileName(self, "导出解密音频副本", str(Path.home() / f"{entry['name']}{entry['extension']}"), "音频文件 (*%s)" % entry["extension"])
        if filename:
            self.library.export(item_id, filename)
            self.status_changed.emit(f"已导出普通音频副本：{filename}")

    def _export_bafen(self) -> None:
        if not self._guard():
            return
        item_id = self._selected_id()
        if not item_id:
            QMessageBox.information(self, "先选择音频", "请选择要封装导出的音频。")
            return
        entry = next(item for item in self.library.items() if item["id"] == item_id)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出八分加密包",
            str(Path.home() / f"{entry['name']}.bfq"),
            "八分加密包 (*.bfq)",
        )
        if not filename:
            return
        password, accepted = QInputDialog.getText(self, "设置八分包口令", "输入口令：", QLineEdit.EchoMode.Password)
        if not accepted:
            return
        if not password:
            QMessageBox.warning(self, "口令为空", "请输入口令后再封装。")
            return
        confirmation, accepted = QInputDialog.getText(self, "确认八分包口令", "再次输入口令：", QLineEdit.EchoMode.Password)
        if not accepted:
            return
        if password != confirmation:
            QMessageBox.warning(self, "口令不一致", "两次输入的口令不一致，请重试。")
            return
        self.set_busy(True)
        try:
            source = self.library.materialize(item_id)
            result = self.bafen.pack(source, password, filename)
            self.status_changed.emit(f"已导出八分加密包：{result.output}")
            QMessageBox.information(self, "八分包已生成", f"音频已封装，原始音频保持不变。\n{result.output}")
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "未能导出八分包", str(exc))
        finally:
            self.set_busy(False)

    def _delete(self) -> None:
        item_id = self._selected_id()
        if item_id and QMessageBox.question(self, "删除音频", "确定从音频库永久删除所选音频吗？此操作不影响已导出的副本。") == QMessageBox.StandardButton.Yes:
            self.player.stop()
            self.library.delete(item_id)
            self.refresh()

    def _encryption_action(self) -> None:
        if self.recorder.recording:
            QMessageBox.information(self, "正在录音", "请先停止并保存录音。")
            return
        if self.library.encryption_enabled and self.library.unlocked:
            self.player.stop()
            self.library.lock()
            self.refresh()
            return
        if self.library.encryption_enabled:
            password, accepted = QInputDialog.getText(self, "解锁音频库", "输入加密密码：", QLineEdit.EchoMode.Password)
            if accepted:
                try:
                    self.library.unlock(password)
                    self.refresh()
                except (InvalidVaultPasswordError, OSError, RuntimeError, ValueError) as exc:
                    QMessageBox.warning(self, "无法解锁或迁移", f"{exc}\n旧音频库仍保留，可检查核心程序和磁盘空间后重试。")
            return
        password, accepted = QInputDialog.getText(self, "启用音频库加密", "设置至少 8 个字符的密码：", QLineEdit.EchoMode.Password)
        if not accepted:
            return
        confirmation, accepted = QInputDialog.getText(self, "确认加密密码", "再次输入密码：", QLineEdit.EchoMode.Password)
        if not accepted:
            return
        if password != confirmation:
            QMessageBox.warning(self, "密码不一致", "两次输入的密码不一致，请重试。")
            return
        try:
            self.library.enable_encryption(password)
            self.refresh()
            QMessageBox.information(self, "观海·八分已启用", "音频、名称、关键词、会议主题和打点均已由观海·八分 BFQ 保护。口令不会保存；遗忘口令将无法恢复内容。\n旧版 AES 库首次以正确密码解锁后会自动迁移。转录或播放时生成会话临时副本，锁定或退出时自动清除。")
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "未能启用加密", str(exc))

    def _disable_encryption(self) -> None:
        password, accepted = QInputDialog.getText(self, "关闭音频库加密", "输入当前密码以解密全部库内音频：", QLineEdit.EchoMode.Password)
        if accepted and QMessageBox.question(self, "确认关闭加密", "关闭后，音频、名称和关键词将以普通文件保存。确定继续吗？") == QMessageBox.StandardButton.Yes:
            try:
                self.library.disable_encryption(password)
                self.refresh()
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.warning(self, "未关闭加密", str(exc))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.setEnabled(not busy)
        self.device_combo.setEnabled(not busy and not self.recorder.recording)
        self.refresh_devices_button.setEnabled(not busy and not self.recorder.recording)
        self.record_button.setEnabled(not busy)

    def shutdown(self) -> None:
        self.meeting_panel.shutdown()
        self.player.stop()
        self.source_chime.stop()
        self.recorder.cancel()
        self.library.lock()
