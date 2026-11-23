from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor, QCloseEvent, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from . import __version__
from .audio_panel import AudioLibraryPanel
from .audio_processing import AUDIO_PRESETS
from .batch import MERGED_MODE, QUEUE_MODE, BatchSummary
from .config import AppConfig, ConfigStore
from .document_export import save_document
from .formatters import export_all, to_json, to_srt, to_vtt
from .minutes import generate_minutes
from .model_catalog import MODEL_SPECS, model_binary_size, model_is_complete
from .paths import APP_ROOT, LOG_ROOT, OUTPUT_ROOT, ensure_data_directories
from .record_naming import read_record_text, rename_record, suggest_name_from_text
from .recording_widgets import LogoTally, RecordingBorder
from .speaker import VoiceprintStore
from .transcriber import TranscriptionResult
from .update_dialog import UpdateConfirmationDialog
from .update_manager import inspect_update, launch_update
from .worker import TranscriptionWorker


MEDIA_FILTER = (
    "音视频文件 (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.wma *.mp4 *.mkv *.mov *.avi *.webm);;"
    "音频文件 (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.wma);;"
    "视频文件 (*.mp4 *.mkv *.mov *.avi *.webm);;所有文件 (*)"
)
LOGO_PATH = APP_ROOT / "assets" / "guanhai-tingtao-logo-256.png"
PRODUCT_NAME = "观海·听涛"


class DropZone(QFrame):
    files_dropped = Signal(list)
    browse_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(104)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(4)
        icon = QLabel("≈")
        icon.setObjectName("dropIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("把音频或视频放在这里")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("支持一次拖入多个文件，或点击多选 · 队列转录／合并文稿")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.browse_requested.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("active", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event):
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        ensure_data_directories()
        self.config_store = ConfigStore()
        self.config = self.config_store.load()
        self.worker: TranscriptionWorker | None = None
        self.result: TranscriptionResult | None = None
        self.result_directory: Path | None = None
        self.batch_directory: Path | None = None
        self.source_paths: list[str] = []
        self.file_statuses: dict[str, str] = {}
        self.queue_outputs: dict[str, str] = {}
        self._update_launch_pending = False
        self.logger = self._create_logger()
        self.setWindowTitle(f"{PRODUCT_NAME} · 本地语音转录")
        self.setMinimumSize(1080, 780)
        self.resize(1260, 880)
        if LOGO_PATH.is_file():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))
        self.setAcceptDrops(True)
        self._build_ui()
        self._load_settings()
        self._refresh_records()
        self._install_shortcuts()

    def _create_logger(self) -> logging.Logger:
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("local_transcriber")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.FileHandler(LOG_ROOT / "app.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
        return logger

    def _build_ui(self) -> None:
        self._apply_palette()
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_workspace())
        self.audio_panel = AudioLibraryPanel()
        self.audio_panel.transcribe_requested.connect(self._add_library_sources)
        self.audio_panel.status_changed.connect(self.status_label.setText)
        self.audio_panel.recording_changed.connect(self._set_recording_tally)
        self.stack.addWidget(self.audio_panel)
        self.stack.addWidget(self._build_records())
        self.stack.addWidget(self._build_system())
        root_layout.addWidget(self.stack, 1)
        self.setStyleSheet(self._stylesheet())
        self._base_window_icon = self.windowIcon()
        self._recording_icon = self._make_recording_icon()
        self.recording_border = RecordingBorder(self)

    def _make_recording_icon(self) -> QIcon:
        source = LOGO_PATH if LOGO_PATH.is_file() else None
        pixmap = QPixmap(str(source)) if source else QPixmap(64, 64)
        if pixmap.isNull():
            pixmap = QPixmap(64, 64)
        pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#E23832"))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawEllipse(42, 4, 19, 19)
        painter.end()
        return QIcon(pixmap)

    def _set_recording_tally(self, active: bool) -> None:
        self.recording_border.set_recording(active)
        self.logo_tally.set_recording(active)
        self.setWindowTitle(("● 录音中 · " if active else "") + f"{PRODUCT_NAME} · 本地语音转录")
        self.setWindowIcon(self._recording_icon if active else self._base_window_icon)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "recording_border"):
            self.recording_border.resize(self.size())

    def _apply_palette(self) -> None:
        application = QApplication.instance()
        if not application:
            return
        application.setStyle("Fusion")
        classical = getattr(self.config, "theme", "classical") == "classical"
        window = QColor("#FFFCF5" if classical else "#FFFFFF")
        text = QColor("#243B3B" if classical else "#203940")
        muted = QColor("#857D6D" if classical else "#71868A")
        border = QColor("#D8CBB4" if classical else "#DCE7E4")
        accent = QColor("#9A6B2F" if classical else "#247B83")
        palette = QPalette()
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.AlternateBase,
                     QPalette.ColorRole.Button, QPalette.ColorRole.ToolTipBase):
            palette.setColor(role, window)
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText,
                     QPalette.ColorRole.ToolTipText):
            palette.setColor(role, text)
        palette.setColor(QPalette.ColorRole.PlaceholderText, muted)
        palette.setColor(QPalette.ColorRole.Mid, border)
        palette.setColor(QPalette.ColorRole.Midlight, border)
        palette.setColor(QPalette.ColorRole.Highlight, accent)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Link, accent)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, muted)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, muted)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, muted)
        application.setPalette(palette)
        application.setStyleSheet(
            f"QDialog, QMessageBox, QInputDialog {{ background: {window.name()}; color: {text.name()}; }}"
            f"QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {{ color: {text.name()}; background: transparent; }}"
            f"QDialog QLineEdit, QDialog QComboBox, QDialog QSpinBox {{ background: {window.name()}; color: {text.name()};"
            f" border: 1px solid {border.name()}; border-radius: 6px; padding: 6px; selection-background-color: {accent.name()}; }}"
            f"QDialog QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {{ background: {window.name()};"
            f" color: {text.name()}; border: 1px solid {border.name()}; border-radius: 6px; padding: 7px 16px; }}"
            f"QDialog QPushButton:hover, QMessageBox QPushButton:hover {{ border-color: {accent.name()}; }}"
        )

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(226)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(20, 26, 20, 22)
        layout.setSpacing(10)
        brand_row = QHBoxLayout()
        self.logo_tally = LogoTally(LOGO_PATH)
        logo = self.logo_tally
        brand_text = QVBoxLayout()
        name = QLabel(PRODUCT_NAME)
        name.setObjectName("brandName")
        caption = QLabel("GUAN HAI · TING TAO")
        caption.setObjectName("brandCaption")
        brand_text.addWidget(name)
        brand_text.addWidget(caption)
        brand_row.addWidget(logo)
        brand_row.addLayout(brand_text)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)
        slogan = QLabel("观海听涛，声落成章")
        slogan.setObjectName("sidebarMuted")
        layout.addWidget(slogan)
        layout.addSpacing(30)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        for index, label in enumerate(("转录工作台", "录音与音频库", "转录记录", "模型与系统")):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, selected=index: self._show_page(selected))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch(1)
        offline = QFrame()
        offline.setObjectName("offlineCard")
        offline_layout = QVBoxLayout(offline)
        offline_title = QLabel("●  完全离线")
        offline_title.setObjectName("offlineTitle")
        offline_text = QLabel("模型、音频与文稿\n都留在当前电脑")
        offline_text.setObjectName("sidebarMuted")
        offline_layout.addWidget(offline_title)
        offline_layout.addWidget(offline_text)
        layout.addWidget(offline)
        version = QLabel(f"山海版  v{__version__}")
        version.setObjectName("sidebarMuted")
        layout.addWidget(version)
        return sidebar

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)

    @staticmethod
    def _page_header(title: str, subtitle: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return layout

    @staticmethod
    def _card() -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        return card, layout

    def _build_workspace(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 20)
        layout.setSpacing(12)
        layout.addLayout(self._page_header("海纳百川，声落成章。", "本地模型逐个识别，多文件不并行争抢内存，转录过程不访问网络。"))

        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self._add_sources)
        self.drop_zone.browse_requested.connect(self._browse_source)
        layout.addWidget(self.drop_zone)

        file_card, file_layout = self._card()
        file_header = QHBoxLayout()
        self.file_summary_label = QLabel("尚未选择文件")
        self.file_summary_label.setObjectName("cardTitle")
        file_header.addWidget(self.file_summary_label)
        file_header.addStretch(1)
        for label, handler in (("添加", self._browse_source), ("移除", self._remove_selected), ("清空", self._clear_sources)):
            button = QPushButton(label)
            button.setObjectName("smallButton")
            button.clicked.connect(handler)
            file_header.addWidget(button)
            if label == "添加":
                self.add_file_button = button
            elif label == "移除":
                self.remove_file_button = button
            else:
                self.clear_files_button = button
        file_layout.addLayout(file_header)
        self.file_list = QListWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setMaximumHeight(112)
        self.file_list.setToolTip("合并模式按此列表顺序生成连续时间轴")
        file_layout.addWidget(self.file_list)
        order_row = QHBoxLayout()
        self.move_up_button = QPushButton("上移")
        self.move_up_button.setObjectName("smallButton")
        self.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.move_down_button = QPushButton("下移")
        self.move_down_button.setObjectName("smallButton")
        self.move_down_button.clicked.connect(lambda: self._move_selected(1))
        order_hint = QLabel("队列独立保存；合并按列表顺序生成一份文稿")
        order_hint.setObjectName("muted")
        order_row.addWidget(self.move_up_button)
        order_row.addWidget(self.move_down_button)
        order_row.addWidget(order_hint)
        order_row.addStretch(1)
        file_layout.addLayout(order_row)
        layout.addWidget(file_card)

        settings_card, settings_layout = self._card()
        settings_grid = QGridLayout()
        settings_grid.setHorizontalSpacing(12)
        settings_grid.setVerticalSpacing(6)
        self.model_combo = QComboBox()
        for key, spec in MODEL_SPECS.items():
            size = model_binary_size(key)
            size_text = f"{size / 1024 / 1024:.0f} MiB" if size else "未安装"
            self.model_combo.addItem(f"{spec.title} · {size_text}", key)
        self.model_combo.setToolTip("每次任务仅加载所选模型；精准模型更细致，但模型、内存和耗时均高于轻量模型")
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("队列逐个转录", QUEUE_MODE)
        self.mode_combo.addItem("合并为一份文稿", MERGED_MODE)
        self.mode_combo.setToolTip("队列：每个文件独立保存；合并：统一时间轴和四种导出")
        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("自动检测", "auto")
        self.language_combo.addItem("英语", "en")
        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 10)
        self.beam_spin.setValue(5)
        self.beam_spin.setToolTip("搜索宽度越大，识别可能更细致，但耗时也会增加")
        self.vad_check = QCheckBox("过滤长时间静音")
        self.vad_check.setChecked(True)
        self.speaker_check = QCheckBox("识别讲话人并匹配声纹库")
        self.speaker_check.setToolTip("按转录片段离线分离；短片段、重叠语音会影响结果")
        self.speaker_threshold = QSpinBox()
        self.speaker_threshold.setRange(30, 90)
        self.speaker_threshold.setSuffix(" %")
        self.speaker_threshold.setValue(55)
        self.speaker_threshold.setToolTip("相似度阈值越高越谨慎；未达到阈值显示未知说话人")
        settings_grid.addWidget(QLabel("识别模型"), 0, 0)
        settings_grid.addWidget(self.model_combo, 1, 0)
        settings_grid.addWidget(QLabel("执行方式"), 0, 1)
        settings_grid.addWidget(self.mode_combo, 1, 1)
        settings_grid.addWidget(QLabel("识别语言"), 0, 2)
        settings_grid.addWidget(self.language_combo, 1, 2)
        settings_grid.addWidget(QLabel("搜索宽度"), 0, 3)
        settings_grid.addWidget(self.beam_spin, 1, 3)
        settings_grid.addWidget(self.vad_check, 1, 4)
        settings_grid.addWidget(self.speaker_check, 2, 0, 1, 3)
        settings_grid.addWidget(QLabel("声纹匹配阈值"), 2, 3)
        settings_grid.addWidget(self.speaker_threshold, 2, 4)
        settings_grid.addWidget(QLabel("转录前声音处理"), 3, 0)
        self.audio_preset_combo = QComboBox()
        for key, preset in AUDIO_PRESETS.items():
            self.audio_preset_combo.addItem(preset["title"], key)
            self.audio_preset_combo.setItemData(self.audio_preset_combo.count() - 1, preset["description"], Qt.ItemDataRole.ToolTipRole)
        self.audio_preset_combo.setToolTip("默认原声；降噪和响度归一化只影响识别用临时音频，不修改原文件。建议先与原声对照。")
        settings_grid.addWidget(self.audio_preset_combo, 3, 1, 1, 2)
        audio_hint = QLabel("不修改原音频 · 降噪可能损失轻声或远场语音")
        audio_hint.setObjectName("muted")
        settings_grid.addWidget(audio_hint, 3, 3, 1, 2)
        settings_grid.setColumnStretch(0, 2)
        settings_grid.setColumnStretch(1, 2)
        settings_grid.setColumnStretch(2, 1)
        settings_grid.setColumnStretch(3, 1)
        settings_layout.addLayout(settings_grid)
        layout.addWidget(settings_card)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("开始转录")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start)
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("准备就绪")
        layout.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("文稿会在这里逐段出现。多文件按列表顺序排列，完成后可直接编辑并另存。")
        self.text_edit.setFont(QFont("Microsoft YaHei UI", 11))
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(1500)
        self.minutes_edit = QPlainTextEdit()
        self.minutes_edit.setPlaceholderText("转录完成后点击“一键形成纪要”，本地自动整理重点、决定事项和待办。")
        self.tabs.addTab(self.text_edit, "转录文稿")
        self.tabs.addTab(self.minutes_edit, "会议纪要")
        self.tabs.addTab(self.log_edit, "运行详情")
        self.tabs.setMaximumWidth(760)
        self.tabs.setMinimumWidth(520)
        layout.addWidget(self.tabs, 1, Qt.AlignmentFlag.AlignHCenter)

        export_row = QHBoxLayout()
        self.export_buttons = {}
        for kind, label in (("txt", "TXT"), ("md", "Markdown"), ("docx", "DOCX／WPS"), ("srt", "SRT"), ("vtt", "VTT"), ("json", "JSON")):
            button = QPushButton(label)
            button.setObjectName("secondaryButton")
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, selected=kind: self._export_as(selected))
            self.export_buttons[kind] = button
            export_row.addWidget(button)
        self.name_speaker_button = QPushButton("命名声纹")
        self.name_speaker_button.setObjectName("secondaryButton")
        self.name_speaker_button.setEnabled(False)
        self.name_speaker_button.clicked.connect(self._name_speakers)
        export_row.addWidget(self.name_speaker_button)
        self.minutes_button = QPushButton("一键形成纪要")
        self.minutes_button.setObjectName("primaryButton")
        self.minutes_button.setEnabled(False)
        self.minutes_button.clicked.connect(self._generate_minutes)
        export_row.addWidget(self.minutes_button)
        self.open_output_button = QPushButton("打开结果目录")
        self.open_output_button.setObjectName("ghostButton")
        self.open_output_button.clicked.connect(self._open_output)
        export_row.addWidget(self.open_output_button)
        export_row.addStretch(1)
        layout.addLayout(export_row)
        self.status_label = QLabel("就绪 · 支持多文件队列与合并文稿")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)
        return page

    def _build_records(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 26, 32, 22)
        layout.setSpacing(16)
        layout.addLayout(self._page_header("转录记录", "单文件、批量队列与合并结果都保存在本地，可在这里查找和打开。"))
        toolbar = QHBoxLayout()
        self.record_search = QLineEdit()
        self.record_search.setPlaceholderText("搜索文件名、批次或日期……")
        self.record_search.textChanged.connect(self._filter_records)
        refresh = QPushButton("刷新")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self._refresh_records)
        open_root = QPushButton("打开总目录")
        open_root.setObjectName("ghostButton")
        open_root.clicked.connect(lambda: self._open_directory(Path(self.output_edit.text() or OUTPUT_ROOT)))
        toolbar.addWidget(self.record_search, 1)
        toolbar.addWidget(refresh)
        toolbar.addWidget(open_root)
        layout.addLayout(toolbar)
        content = QHBoxLayout()
        self.record_list = QListWidget()
        self.record_list.setObjectName("recordList")
        self.record_list.itemSelectionChanged.connect(self._show_selected_record)
        self.record_detail = QPlainTextEdit()
        self.record_detail.setReadOnly(True)
        self.record_detail.setPlaceholderText("选择左侧记录，查看已保存的文稿。")
        content.addWidget(self.record_list, 2)
        content.addWidget(self.record_detail, 3)
        layout.addLayout(content, 1)
        self.open_record_button = QPushButton("打开所选结果目录")
        self.open_record_button.setObjectName("secondaryButton")
        self.open_record_button.clicked.connect(self._open_selected_record)
        self.open_record_button.setEnabled(False)
        record_actions = QHBoxLayout()
        record_actions.addWidget(self.open_record_button)
        self.rename_record_button = QPushButton("重命名")
        self.rename_record_button.setObjectName("secondaryButton")
        self.rename_record_button.setEnabled(False)
        self.rename_record_button.clicked.connect(lambda: self._rename_selected_record(False))
        self.auto_name_button = QPushButton("根据内容命名")
        self.auto_name_button.setObjectName("secondaryButton")
        self.auto_name_button.setEnabled(False)
        self.auto_name_button.clicked.connect(lambda: self._rename_selected_record(True))
        record_actions.addWidget(self.rename_record_button)
        record_actions.addWidget(self.auto_name_button)
        record_actions.addStretch(1)
        layout.addLayout(record_actions)
        return page

    def _build_system(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 26, 32, 22)
        layout.setSpacing(14)
        layout.addLayout(self._page_header("模型与系统", "资源透明、皮肤可选、升级可控，不以部署尺寸换取不确定的收益。"))

        model_card, model_layout = self._card()
        model_title = QLabel("内置识别模型与资源规划")
        model_title.setObjectName("cardTitle")
        model_layout.addWidget(model_title)
        model_row = QHBoxLayout()
        small_size = model_binary_size("small") / 1024 / 1024
        medium_size = model_binary_size("medium") / 1024 / 1024
        medium_status = "已内置" if model_is_complete("medium") else "未安装"
        for value, caption in (("轻量／精准", "工作台可切换"), (f"{small_size + medium_size:.0f} MiB", "双模型文件总量"), (medium_status, "精准离线模型"), ("单模型驻留", "队列复用同一实例")):
            item = QVBoxLayout()
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            caption_label = QLabel(caption)
            caption_label.setObjectName("muted")
            item.addWidget(value_label)
            item.addWidget(caption_label)
            model_row.addLayout(item, 1)
        model_layout.addLayout(model_row)
        voiceprint_button = QPushButton("管理持久声纹库")
        voiceprint_button.setObjectName("secondaryButton")
        voiceprint_button.clicked.connect(self._manage_voiceprints)
        model_layout.addWidget(voiceprint_button, alignment=Qt.AlignmentFlag.AlignLeft)
        policy = QLabel(
            "轻量模型适合快速日常转录；精准模型适合精度优先任务。每次任务只加载所选模型，不会同时驻留两个模型。"
            "精准模型资源规划（非通用实测承诺）：峰值内存按 3–5 GB、CPU 时间按轻量模型的约 2–4 倍预留。"
            "超大模型未内置；其文件约 3.09 GB，规划峰值内存 6–10 GB。长音频、CPU 和搜索宽度会显著影响实际值。"
        )
        policy.setObjectName("muted")
        policy.setWordWrap(True)
        model_layout.addWidget(policy)
        layout.addWidget(model_card)

        output_card, output_layout = self._card()
        output_title = QLabel("结果保存位置")
        output_title.setObjectName("cardTitle")
        output_layout.addWidget(output_title)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        output_button = QPushButton("更改目录")
        output_button.setObjectName("secondaryButton")
        output_button.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(output_button)
        output_layout.addLayout(output_row)
        layout.addWidget(output_card)

        theme_card, theme_layout = self._card()
        theme_row = QHBoxLayout()
        theme_text = QVBoxLayout()
        theme_title = QLabel("界面皮肤")
        theme_title.setObjectName("cardTitle")
        theme_hint = QLabel("山海古典使用宣纸、黛青、赭金与古典标题字体；素简现代保留清爽浅色。")
        theme_hint.setObjectName("muted")
        theme_text.addWidget(theme_title)
        theme_text.addWidget(theme_hint)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("山海古典", "classical")
        self.theme_combo.addItem("素简现代", "modern")
        self.theme_combo.currentIndexChanged.connect(self._change_theme)
        theme_row.addLayout(theme_text, 1)
        theme_row.addWidget(self.theme_combo)
        theme_layout.addLayout(theme_row)
        layout.addWidget(theme_card)

        update_card, update_layout = self._card()
        update_title = QLabel("离线增量升级")
        update_title.setObjectName("cardTitle")
        update_layout.addWidget(update_title)
        update_description = QLabel(
            f"当前版本 v{__version__}。直接选择收到的增量 ZIP 或 .ttupdate，无需解压，也不用处理 manifest。\n"
            "读取后展示发行说明；确认即可校验、备份并一键升级，失败自动回滚。配置、音频库、记录和已有模型受保护。"
        )
        update_description.setObjectName("muted")
        update_description.setWordWrap(True)
        update_layout.addWidget(update_description)
        self.update_button = QPushButton("导入离线增量包")
        self.update_button.setObjectName("primaryButton")
        self.update_button.clicked.connect(self._import_update)
        update_layout.addWidget(self.update_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(update_card)
        layout.addStretch(1)
        return page

    def _stylesheet(self) -> str:
        classical = getattr(self.config, "theme", "classical") == "classical"
        colors = {
            "window": "#F2ECDF" if classical else "#F3F7F6",
            "card": "#FFFCF5" if classical else "#FFFFFF",
            "sidebar": "#17383D" if classical else "#173B4B",
            "sidebar_card": "#21464A" if classical else "#1D4654",
            "text": "#243B3B" if classical else "#203940",
            "title": "#17383D" if classical else "#173B4B",
            "muted": "#857D6D" if classical else "#71868A",
            "accent": "#9A6B2F" if classical else "#247B83",
            "accent_dark": "#765022" if classical else "#1B6870",
            "border": "#D8CBB4" if classical else "#DCE7E4",
            "soft": "#E9E0CE" if classical else "#E9F2F0",
            "hover": "#E8DECA" if classical else "#EAF3F1",
        }
        title_font = "'STKaiti','KaiTi','Noto Serif CJK SC','AR PL UKai CN',serif" if classical else "'Microsoft YaHei UI'"
        body_font = "'Noto Serif CJK SC','Source Han Serif SC','SimSun','Microsoft YaHei UI',serif" if classical else "'Microsoft YaHei UI'"
        return f"""
            QMainWindow, QWidget#central {{ background: {colors['window']}; color: {colors['text']}; font-family: {body_font}; font-size: 13px; }}
            QFrame#sidebar {{ background: {colors['sidebar']}; }}
            QLabel#brandName {{ color: #F7F0DF; font-family: {title_font}; font-size: 24px; font-weight: 700; }}
            QLabel#brandCaption {{ color: #C8B991; font-size: 8px; letter-spacing: 1px; }}
            QLabel#sidebarMuted {{ color: #C8C2AD; font-size: 11px; }}
            QPushButton#navButton {{ color: #DDD7C5; background: transparent; border: none; border-radius: 7px; text-align: left; padding: 12px 15px; font-size: 14px; }}
            QPushButton#navButton:hover {{ background: #2A5052; color: white; }}
            QPushButton#navButton:checked {{ background: {colors['accent']}; color: white; font-weight: 600; }}
            QFrame#offlineCard {{ background: {colors['sidebar_card']}; border: 1px solid #52665F; border-radius: 9px; padding: 10px; }}
            QLabel#offlineTitle {{ color: #D6C28D; font-weight: 600; }}
            QLabel#pageTitle {{ color: {colors['title']}; font-family: {title_font}; font-size: 27px; font-weight: 700; }}
            QLabel#pageSubtitle {{ color: {colors['muted']}; font-size: 12px; }}
            QFrame#card {{ background: {colors['card']}; border: 1px solid {colors['border']}; border-radius: 10px; }}
            QLabel#cardTitle {{ color: {colors['title']}; font-family: {title_font}; font-size: 16px; font-weight: 600; }}
            QLabel#muted {{ color: {colors['muted']}; font-size: 11px; }}
            QLabel#metricValue {{ color: {colors['accent']}; font-size: 18px; font-weight: 700; }}
            QFrame#dropZone {{ background: {colors['soft']}; border: 1.5px dashed {colors['accent']}; border-radius: 12px; }}
            QFrame#dropZone[active="true"] {{ background: {colors['hover']}; border: 2px solid {colors['accent']}; }}
            QLabel#dropIcon {{ color: {colors['accent']}; font-family: 'Segoe UI'; font-size: 34px; font-weight: 300; }}
            QLabel#dropTitle {{ color: {colors['title']}; font-family: {title_font}; font-size: 18px; font-weight: 600; }}
            QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {{ color: {colors['text']}; background: {colors['card']}; border: 1px solid {colors['border']}; border-radius: 7px; padding: 7px; selection-background-color: {colors['accent']}; selection-color: #FFFFFF; }}
            QComboBox QAbstractItemView {{ background: {colors['card']}; color: {colors['text']}; selection-background-color: {colors['accent']}; selection-color: #FFFFFF; border: 1px solid {colors['border']}; outline: none; padding: 4px; }}
            QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 4px 8px; background: {colors['card']}; color: {colors['text']}; }}
            QComboBox QAbstractItemView::item:selected {{ background: {colors['accent']}; color: #FFFFFF; }}
            QPlainTextEdit {{ padding: 12px; }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {colors['accent']}; }}
            QListWidget#fileList::item {{ padding: 4px; border-bottom: 1px solid {colors['soft']}; }}
            QListWidget#fileList::item:selected {{ background: {colors['soft']}; color: {colors['title']}; }}
            QPushButton {{ border-radius: 7px; padding: 8px 15px; min-height: 20px; font-weight: 500; }}
            QPushButton#primaryButton {{ background: {colors['accent']}; color: white; border: none; padding-left: 22px; padding-right: 22px; }}
            QPushButton#primaryButton:hover {{ background: {colors['accent_dark']}; }}
            QPushButton#secondaryButton {{ background: {colors['card']}; color: {colors['title']}; border: 1px solid {colors['border']}; }}
            QPushButton#secondaryButton:hover, QPushButton#smallButton:hover {{ background: {colors['hover']}; border-color: {colors['accent']}; }}
            QPushButton#smallButton {{ background: transparent; color: {colors['title']}; border: 1px solid {colors['border']}; padding: 4px 10px; min-height: 16px; }}
            QPushButton#ghostButton {{ background: transparent; color: {colors['accent']}; border: none; }}
            QPushButton#ghostButton:hover {{ background: {colors['hover']}; }}
            QPushButton:disabled {{ color: #A39D90; background: #E8E3D9; border-color: {colors['border']}; }}
            QProgressBar {{ background: {colors['soft']}; border: none; border-radius: 7px; height: 20px; text-align: center; color: {colors['title']}; }}
            QProgressBar::chunk {{ background: {colors['accent']}; border-radius: 7px; }}
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{ color: {colors['muted']}; background: {colors['soft']}; padding: 8px 18px; margin-right: 4px; border-top-left-radius: 7px; border-top-right-radius: 7px; }}
            QTabBar::tab:selected {{ background: {colors['card']}; color: {colors['accent']}; font-weight: 600; }}
            QListWidget#recordList::item {{ padding: 10px; border-bottom: 1px solid {colors['soft']}; }}
            QListWidget#recordList::item:selected {{ background: {colors['soft']}; color: {colors['title']}; }}
            QCheckBox {{ color: {colors['text']}; spacing: 8px; }}
            QToolTip {{ background: {colors['sidebar']}; color: white; border: none; padding: 7px; }}
        """

    def _install_shortcuts(self) -> None:
        for sequence, handler in (("Ctrl+O", self._browse_source), ("Ctrl+Return", self._start), ("Ctrl+S", lambda: self._export_as("txt"))):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(handler)

    def _load_settings(self) -> None:
        index = self.language_combo.findData(self.config.language)
        self.language_combo.setCurrentIndex(max(0, index))
        self.beam_spin.setValue(self.config.beam_size)
        self.vad_check.setChecked(self.config.vad_filter)
        self.speaker_check.setChecked(getattr(self.config, "speaker_enabled", False))
        self.speaker_threshold.setValue(round(getattr(self.config, "speaker_threshold", 0.55) * 100))
        self.output_edit.setText(self.config.output_directory or str(OUTPUT_ROOT))
        mode_index = self.mode_combo.findData(getattr(self.config, "batch_mode", QUEUE_MODE))
        self.mode_combo.setCurrentIndex(max(0, mode_index))
        theme_index = self.theme_combo.findData(getattr(self.config, "theme", "classical"))
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        model_index = self.model_combo.findData(getattr(self.config, "model_name", "small"))
        self.model_combo.setCurrentIndex(max(0, model_index))
        preset_index = self.audio_preset_combo.findData(getattr(self.config, "audio_preset", "original"))
        self.audio_preset_combo.setCurrentIndex(max(0, preset_index))

    def _current_config(self) -> AppConfig:
        return AppConfig(
            language=str(self.language_combo.currentData()),
            beam_size=self.beam_spin.value(),
            vad_filter=self.vad_check.isChecked(),
            output_directory=self.output_edit.text().strip() or str(OUTPUT_ROOT),
            batch_mode=str(self.mode_combo.currentData()),
            theme=str(self.theme_combo.currentData()),
            model_name=str(self.model_combo.currentData()),
            speaker_enabled=self.speaker_check.isChecked(),
            speaker_threshold=self.speaker_threshold.value() / 100,
            audio_preset=str(self.audio_preset_combo.currentData()),
        )

    def _change_theme(self) -> None:
        self.config.theme = str(self.theme_combo.currentData())
        self._apply_palette()
        self.setStyleSheet(self._stylesheet())

    def _add_sources(self, paths: list[str]) -> None:
        if self.worker and self.worker.isRunning():
            return
        added = 0
        for value in paths:
            source = Path(value)
            if not source.is_file():
                continue
            resolved = str(source.resolve())
            if resolved in self.source_paths:
                continue
            self.source_paths.append(resolved)
            self.file_statuses[resolved] = "等待"
            added += 1
        self._refresh_file_list()
        if added:
            self._append_log(f"已添加 {added} 个文件，当前共 {len(self.source_paths)} 个")

    def _add_library_sources(self, paths: list[str]) -> None:
        self._add_sources(paths)
        self._show_page(0)
        self.status_label.setText(f"已从音频库加入 {len(paths)} 个音频 · 点击开始转录即可离线识别")

    def _set_source(self, path: str) -> None:
        self.source_paths.clear()
        self.file_statuses.clear()
        self._add_sources([path])

    def _refresh_file_list(self) -> None:
        selected = self.file_list.currentRow()
        self.file_list.clear()
        for index, source in enumerate(self.source_paths):
            path = Path(source)
            status = self.file_statuses.get(source, "等待")
            item = QListWidgetItem(f"{index + 1:02d}  {path.name}  ·  {status}\n     {path.parent}")
            item.setData(Qt.ItemDataRole.UserRole, source)
            item.setToolTip(str(path))
            self.file_list.addItem(item)
        if self.source_paths:
            self.file_list.setCurrentRow(max(0, min(selected, len(self.source_paths) - 1)))
        self.file_summary_label.setText(f"已选择 {len(self.source_paths)} 个文件" if self.source_paths else "尚未选择文件")

    def _browse_source(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        filenames, _ = QFileDialog.getOpenFileNames(self, "选择一个或多个音频／视频", self.source_paths[-1] if self.source_paths else "", MEDIA_FILTER)
        if filenames:
            self._add_sources(filenames)

    def _remove_selected(self) -> None:
        rows = sorted((index.row() for index in self.file_list.selectedIndexes()), reverse=True)
        for row in rows:
            source = self.source_paths.pop(row)
            self.file_statuses.pop(source, None)
        self._refresh_file_list()

    def _clear_sources(self) -> None:
        self.source_paths.clear()
        self.file_statuses.clear()
        self._refresh_file_list()

    def _move_selected(self, delta: int) -> None:
        row = self.file_list.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= len(self.source_paths):
            return
        self.source_paths[row], self.source_paths[target] = self.source_paths[target], self.source_paths[row]
        self._refresh_file_list()
        self.file_list.setCurrentRow(target)

    def _browse_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择结果保存目录", self.output_edit.text())
        if directory:
            self.output_edit.setText(directory)

    def _append_log(self, message: str) -> None:
        self.log_edit.appendPlainText(f"[{datetime.now():%H:%M:%S}] {message}")
        self.logger.info(message)

    def _set_running(self, running: bool) -> None:
        self.audio_panel.set_busy(running)
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.drop_zone.setEnabled(not running)
        for widget in (
            self.model_combo, self.language_combo, self.beam_spin, self.vad_check, self.mode_combo,
            self.speaker_check, self.speaker_threshold, self.audio_preset_combo,
            self.output_edit, self.update_button, self.file_list, self.add_file_button,
            self.remove_file_button, self.clear_files_button, self.move_up_button, self.move_down_button,
        ):
            widget.setEnabled(not running)

    @staticmethod
    def _safe_stem(value: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', "_", Path(value).stem).strip() or "transcript"

    def _start(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        if not self.source_paths:
            self._show_page(0)
            QMessageBox.information(self, "先选择声音文件", "可一次拖入或多选多个音频／视频文件。\nCtrl+O 打开，Ctrl+Enter 开始。")
            return
        selected_model = str(self.model_combo.currentData())
        if not model_is_complete(selected_model):
            QMessageBox.critical(self, "模型文件不完整", f"本地 {selected_model} 模型未安装或文件不完整，请检查 models 目录。")
            return
        output = Path(self.output_edit.text().strip() or str(OUTPUT_ROOT))
        try:
            output.mkdir(parents=True, exist_ok=True)
            self.config = self._current_config()
            self.config_store.save(self.config)
        except OSError as exc:
            QMessageBox.critical(self, "目录不可用", str(exc))
            return
        self._show_page(0)
        self.result = None
        self.result_directory = None
        self.queue_outputs.clear()
        self.text_edit.clear()
        self.minutes_edit.clear()
        self.log_edit.clear()
        self.name_speaker_button.setEnabled(False)
        self.minutes_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setFormat("正在准备本地模型……")
        self.status_label.setText("任务运行中 · 模型只加载一次，文件按队列顺序处理")
        for button in self.export_buttons.values():
            button.setEnabled(False)
        for source in self.source_paths:
            self.file_statuses[source] = "等待"
        self._refresh_file_list()
        prefix = "合并" if self.config.batch_mode == MERGED_MODE else "批量"
        self.batch_directory = output / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}"
        suffix = 1
        while self.batch_directory.exists():
            suffix += 1
            self.batch_directory = output / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{suffix}"
        self.batch_directory.mkdir(parents=True)
        self._append_log(f"识别模型：{self.config.model_name}；执行方式：{self.config.batch_mode}；文件数：{len(self.source_paths)}")
        self._set_running(True)
        self.worker = TranscriptionWorker(
            self.source_paths, self.config.language, self.config.beam_size, self.config.vad_filter,
            self.config.batch_mode, self.config.model_name,
            speaker_enabled=self.config.speaker_enabled,
            speaker_threshold=self.config.speaker_threshold,
            audio_preset=self.config.audio_preset, parent=self,
        )
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.segment_ready.connect(self._on_segment)
        self.worker.log_ready.connect(self._append_log)
        self.worker.file_started.connect(self._on_file_started)
        self.worker.file_completed.connect(self._on_file_completed)
        self.worker.file_failed.connect(self._on_file_failed)
        self.worker.succeeded.connect(self._on_succeeded)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("正在安全停止，将在当前识别片段结束后取消……")

    def _on_progress(self, value: int, message: str) -> None:
        self.progress.setValue(value)
        self.progress.setFormat(f"{message} · %p%")

    def _on_segment(self, segment) -> None:
        text = segment.text.strip()
        if text:
            self.text_edit.appendPlainText(text)

    def _set_file_status(self, index: int, status: str) -> None:
        if 0 <= index < len(self.source_paths):
            source = self.source_paths[index]
            self.file_statuses[source] = status
            self._refresh_file_list()

    def _on_file_started(self, source: str, index: int, total: int) -> None:
        self._set_file_status(index, "识别中")
        self.text_edit.appendPlainText(f"\n【{Path(source).name}】")

    def _on_file_completed(self, result: TranscriptionResult, index: int, total: int) -> None:
        self._set_file_status(index, "完成")
        if self.config.batch_mode == QUEUE_MODE and self.batch_directory:
            folder = self.batch_directory / f"{index + 1:02d}_{self._safe_stem(result.source)}"
            export_all(result, folder, self._safe_stem(result.source))
            self.queue_outputs[result.source] = str(folder)
            self._append_log(f"已独立保存：{folder}")

    def _on_file_failed(self, source: str, error: str, index: int, total: int) -> None:
        self._set_file_status(index, "失败")
        self._append_log(f"文件失败但队列继续：{Path(source).name}；{error}")

    def _on_succeeded(self, summary: BatchSummary) -> None:
        self.result = summary.merged_result
        if self.batch_directory:
            stem = "合并文稿" if summary.mode == MERGED_MODE else "批次汇总"
            export_all(self.result, self.batch_directory, stem)
            report = {
                "mode": summary.mode,
                "succeeded": summary.succeeded_count,
                "failed": summary.failed_count,
                "sources": [result.source for result in summary.results],
                "failures": [failure.to_dict() for failure in summary.failures],
                "individual_outputs": self.queue_outputs,
                "summary_output": str(self.batch_directory),
            }
            (self.batch_directory / "batch-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            self.result_directory = self.batch_directory
        self.status_label.setText(f"批量完成 · 成功 {summary.succeeded_count} 个 · 失败 {summary.failed_count} 个 · 结果已保存")
        self.progress.setValue(100)
        self.progress.setFormat("批量转录完成")
        for button in self.export_buttons.values():
            button.setEnabled(True)
        self.text_edit.setPlainText(self.result.text)
        self.name_speaker_button.setEnabled(bool(self.result.speaker_embeddings))
        self.minutes_button.setEnabled(True)
        self._set_running(False)
        self._refresh_records()
        if summary.failed_count:
            QMessageBox.warning(self, "部分文件未完成", f"成功 {summary.succeeded_count} 个，失败 {summary.failed_count} 个。\n失败原因已写入运行详情和 batch-report.json。")

    def _on_failed(self, message: str) -> None:
        self._append_log(f"错误：{message}")
        self.progress.setFormat("转录未完成")
        self.status_label.setText("转录失败 · 可在运行详情中查看原因")
        self._set_running(False)
        QMessageBox.critical(self, "转录未完成", message)

    def _on_cancelled(self) -> None:
        self._append_log("任务已由用户取消")
        self.progress.setValue(0)
        self.progress.setFormat("已取消")
        self.status_label.setText("任务已取消，已完成的独立文件不会受影响")
        self._set_running(False)

    def _export_as(self, kind: str) -> None:
        if not self.result:
            return
        suffix = f".{kind}"
        exporting_minutes = self.tabs.currentWidget() == self.minutes_edit and bool(self.minutes_edit.toPlainText().strip())
        title = "观海听涛纪要" if exporting_minutes else "观海听涛文稿"
        initial_directory = self.result_directory or Path(self.output_edit.text() or OUTPUT_ROOT)
        initial = initial_directory / f"{title}{suffix}"
        filters = {
            "txt": "文本文件 (*.txt)", "md": "Markdown 文件 (*.md)",
            "docx": "Word／WPS 文字文档 (*.docx)", "srt": "SRT 字幕 (*.srt)",
            "vtt": "WebVTT 字幕 (*.vtt)", "json": "JSON 数据 (*.json)",
        }
        filename, _ = QFileDialog.getSaveFileName(self, f"导出 {kind.upper()}", str(initial), filters[kind])
        if not filename:
            return
        try:
            if kind in {"txt", "md", "docx"}:
                content = self.minutes_edit.toPlainText() if exporting_minutes else self.text_edit.toPlainText()
                save_document(filename, content, title)
            else:
                content = {
                    "srt": lambda: to_srt(self.result),
                    "vtt": lambda: to_vtt(self.result),
                    "json": lambda: to_json(self.result, self.text_edit.toPlainText()),
                }[kind]()
                Path(filename).write_text(content, encoding="utf-8")
            self._append_log(f"已导出：{filename}")
            self.status_label.setText(f"已导出 {kind.upper()} · {filename}")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    @staticmethod
    def _open_directory(directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _open_output(self) -> None:
        self._open_directory(self.result_directory or Path(self.output_edit.text() or OUTPUT_ROOT))

    def _refresh_records(self) -> None:
        root = Path(self.output_edit.text() or OUTPUT_ROOT)
        records = []
        if root.is_dir():
            for folder in root.iterdir():
                if folder.is_dir() and any(folder.glob("*.json")):
                    records.append(folder)
        records.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        self.record_list.clear()
        for folder in records:
            modified = datetime.fromtimestamp(folder.stat().st_mtime)
            item = QListWidgetItem(f"{folder.name}\n{modified:%Y-%m-%d %H:%M}")
            item.setData(Qt.ItemDataRole.UserRole, str(folder))
            self.record_list.addItem(item)
        self._filter_records()

    def _filter_records(self) -> None:
        query = self.record_search.text().strip().lower()
        for index in range(self.record_list.count()):
            item = self.record_list.item(index)
            item.setHidden(query not in item.text().lower())

    def _selected_record_folder(self) -> Path | None:
        items = self.record_list.selectedItems()
        return Path(items[0].data(Qt.ItemDataRole.UserRole)) if items else None

    def _show_selected_record(self) -> None:
        folder = self._selected_record_folder()
        self.open_record_button.setEnabled(folder is not None)
        self.rename_record_button.setEnabled(folder is not None)
        self.auto_name_button.setEnabled(folder is not None)
        if not folder:
            return
        preferred = list(folder.glob("合并文稿.txt")) + list(folder.glob("批次汇总.txt")) + list(folder.glob("*.txt"))
        if preferred:
            self.record_detail.setPlainText(preferred[0].read_text(encoding="utf-8-sig"))
            return
        json_files = [path for path in folder.glob("*.json") if path.name != "batch-report.json"]
        if json_files:
            payload = json.loads(json_files[0].read_text(encoding="utf-8"))
            self.record_detail.setPlainText(payload.get("text", ""))

    def _open_selected_record(self) -> None:
        folder = self._selected_record_folder()
        if folder:
            self._open_directory(folder)

    def _rename_selected_record(self, automatic: bool) -> None:
        folder = self._selected_record_folder()
        if not folder:
            return
        suggested = suggest_name_from_text(read_record_text(folder)) if automatic else folder.name
        if automatic and not suggested:
            QMessageBox.information(self, "无法自动命名", "文稿中没有可用标题或有效正文，请使用“重命名”手动输入。")
            return
        name, accepted = QInputDialog.getText(self, "根据内容命名" if automatic else "重命名记录", "记录名称：", text=suggested)
        if not accepted:
            return
        try:
            destination = rename_record(folder, name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "重命名未完成", str(exc))
            return
        self._refresh_records()
        matches = self.record_list.findItems(destination.name, Qt.MatchFlag.MatchStartsWith)
        if matches:
            self.record_list.setCurrentItem(matches[0])
        self.status_label.setText(f"记录已命名为：{destination.name}")

    def _name_speakers(self) -> None:
        if not self.result or not self.result.speaker_embeddings:
            return
        keys = list(self.result.speaker_embeddings)
        labels = []
        for key in keys:
            index, _separator, speaker = key.partition(":")
            source_index = int(index)
            source = Path(self.result.sources[source_index]).name if source_index < len(self.result.sources) else "音频"
            labels.append(f"{source} · {speaker}")
        selected, accepted = QInputDialog.getItem(self, "命名当前讲话人", "选择要保存到声纹库的讲话人：", labels, 0, False)
        if not accepted:
            return
        key = keys[labels.index(selected)]
        source_index, _separator, original_speaker = key.partition(":")
        name, accepted = QInputDialog.getText(self, "保存持久声纹", "讲话人姓名：")
        if not accepted or not name.strip():
            return
        try:
            VoiceprintStore().add(name, [self.result.speaker_embeddings[key]])
            index = int(source_index)
            segments = tuple(
                replace(segment, speaker=name.strip()) if segment.speaker == original_speaker and segment.source_index == index else segment
                for segment in self.result.segments
            )
            self.result = replace(self.result, segments=segments)
            if self.result_directory:
                stem = "合并文稿" if self.result.batch_mode == MERGED_MODE else "批次汇总"
                export_all(self.result, self.result_directory, stem)
            self.text_edit.setPlainText(self.result.text)
            self._append_log(f"已将 {original_speaker} 保存为持久声纹：{name.strip()}")
            QMessageBox.information(self, "声纹已保存", "以后开启讲话人识别时，将自动匹配该姓名。\n短片段和重叠语音仍可能无法可靠匹配。")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "声纹未保存", str(exc))

    def _manage_voiceprints(self) -> None:
        store = VoiceprintStore()
        dialog = QDialog(self)
        dialog.setWindowTitle("持久声纹库")
        dialog.resize(440, 380)
        layout = QVBoxLayout(dialog)
        hint = QLabel("声纹仅保存在本机 data 目录，升级不会覆盖。\n选择记录后可重命名或删除；新转录会自动匹配。")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        voice_list = QListWidget()
        layout.addWidget(voice_list, 1)
        buttons = QHBoxLayout()
        rename_button = QPushButton("重命名")
        delete_button = QPushButton("删除")
        close_button = QPushButton("关闭")
        for button in (rename_button, delete_button, close_button):
            button.setObjectName("secondaryButton")
            buttons.addWidget(button)
        layout.addLayout(buttons)
        def refresh() -> None:
            voice_list.clear()
            for name, vectors in store.load().items():
                voice_list.addItem(f"{name}  ·  {len(vectors)} 份声纹")
        def selected_name() -> str:
            item = voice_list.currentItem()
            return item.text().split("  ·  ", 1)[0] if item else ""
        def rename_voice() -> None:
            old = selected_name()
            if not old:
                return
            new, accepted = QInputDialog.getText(dialog, "重命名声纹", "姓名：", text=old)
            if accepted:
                try:
                    store.rename(old, new)
                    refresh()
                except (OSError, ValueError) as exc:
                    QMessageBox.warning(dialog, "未重命名", str(exc))
        def delete_voice() -> None:
            name = selected_name()
            if name and QMessageBox.question(dialog, "删除声纹", f"确定删除“{name}”吗？转录记录不受影响。") == QMessageBox.StandardButton.Yes:
                store.delete(name)
                refresh()
        rename_button.clicked.connect(rename_voice)
        delete_button.clicked.connect(delete_voice)
        close_button.clicked.connect(dialog.accept)
        refresh()
        dialog.exec()

    def _generate_minutes(self) -> None:
        if not self.result:
            return
        content = generate_minutes(self.result, self.text_edit.toPlainText())
        self.minutes_edit.setPlainText(content)
        self.tabs.setCurrentWidget(self.minutes_edit)
        if self.result_directory:
            path = self.result_directory / "会议纪要.md"
            path.write_text(content, encoding="utf-8-sig")
            self.status_label.setText(f"纪要已保存：{path.name} · 请结合原文复核")

    def _import_update(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "任务正在运行", "请等待批量转录完成或取消任务后再升级。")
            return
        package, _ = QFileDialog.getOpenFileName(
            self, "选择离线增量升级包", str(APP_ROOT),
            "观海听涛增量升级包 (*.zip *.ttupdate);;增量 ZIP (*.zip);;单一升级载荷 (*.ttupdate);;所有文件 (*)",
        )
        if not package:
            return
        try:
            manifest = inspect_update(package)
        except Exception as exc:
            QMessageBox.critical(self, "升级包不可用", str(exc))
            return
        dialog = UpdateConfirmationDialog(manifest, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.update_button.setEnabled(False)
        self.status_label.setText("正在准备内嵌升级 · 主窗口关闭后将自动安装并启动新版")
        QApplication.processEvents()
        try:
            import sys
            # Save the selected theme and all other settings before the UI closes.
            self.config_store.save(self._current_config())
            staged = launch_update(package)
            if not getattr(sys, "frozen", False):
                from .update_engine import apply_update
                report = apply_update(staged, APP_ROOT)
                QMessageBox.information(self, "升级完成", f"已升级至 v{report['to_version']}，请重新启动程序。")
                return
        except Exception as exc:
            self.update_button.setEnabled(True)
            self.status_label.setText("升级尚未开始 · 个人数据保持不变")
            QMessageBox.critical(self, "升级未完成", f"{exc}\n尚未替换程序文件，个人数据保持不变。")
            return
        self.audio_panel.shutdown()
        self._update_launch_pending = True
        self.close()

    def dragEnterEvent(self, event) -> None:
        running = self.worker is not None and self.worker.isRunning()
        if event.mimeData().hasUrls() and not running:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self._show_page(0)
            self._add_sources(paths)
            event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._update_launch_pending and self.worker and self.worker.isRunning():
            answer = QMessageBox.question(self, "任务仍在运行", "确定取消当前批量转录并退出吗？")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.cancel()
            if not self.worker.wait(5000):
                QMessageBox.information(self, "正在取消", "请等待当前识别片段结束后再次关闭窗口。")
                event.ignore()
                return
        self.audio_panel.shutdown()
        try:
            self.config_store.save(self._current_config())
        except OSError:
            pass
        event.accept()
