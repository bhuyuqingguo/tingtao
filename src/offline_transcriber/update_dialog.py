from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout,
)

from .paths import APP_ROOT


class UpdateConfirmationDialog(QDialog):
    """A readable release-note page before the embedded one-click update."""

    def __init__(self, manifest: dict, parent=None):
        super().__init__(parent)
        self.manifest = manifest
        self.setWindowTitle("观海·听涛 · 离线增量升级")
        self.setMinimumSize(640, 570)
        self.resize(680, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(16)

        heading = QHBoxLayout()
        heading.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(APP_ROOT / "assets" / "guanhai-tingtao-logo-64.png")))
        logo.setFixedSize(64, 64)
        logo.setScaledContents(True)
        heading.addWidget(logo)
        title_column = QVBoxLayout()
        title_column.setSpacing(4)
        title = QLabel("江海有时，新篇将至")
        title.setObjectName("updateTitle")
        title_column.addWidget(title)
        source = "已直接读取增量 ZIP，无需解压" if manifest.get("distribution_path") else "已读取单一升级载荷"
        subtitle = QLabel(f"{source} · 文件完整性校验通过")
        subtitle.setObjectName("updateSubtitle")
        subtitle.setWordWrap(True)
        title_column.addWidget(subtitle)
        heading.addLayout(title_column, 1)
        root.addLayout(heading)

        version = QLabel(f"v{manifest['from_version']}  <span style='color:#A78C5B'>→</span>  <span style='color:#287A75'>v{manifest['to_version']}</span>")
        version.setTextFormat(Qt.TextFormat.RichText)
        version.setObjectName("updateVersion")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(version)

        size_mb = manifest["total_payload_bytes"] / 1024 / 1024
        kind = manifest.get("package_kind")
        model_note = "；新增 medium 模型" if kind == "application-with-model" else ("；新增中文声纹模型" if kind == "application-with-voiceprint" else "")
        facts = QLabel(f"更新文件　{len(manifest['files'])} 项　　 净载荷　{size_mb:.1f} MiB{model_note}")
        facts.setObjectName("updateFacts")
        facts.setAlignment(Qt.AlignmentFlag.AlignCenter)
        facts.setWordWrap(True)
        root.addWidget(facts)

        notes_card = QFrame()
        notes_card.setObjectName("updateNotesCard")
        notes_layout = QVBoxLayout(notes_card)
        notes_layout.setContentsMargins(18, 14, 18, 14)
        notes_title = QLabel("本版发行说明")
        notes_title.setObjectName("updateNotesTitle")
        notes_layout.addWidget(notes_title)
        notes = QTextBrowser()
        notes.setObjectName("updateNotes")
        notes.setOpenExternalLinks(False)
        notes.setReadOnly(True)
        notes.setHtml(self._notes_html(manifest.get("release_notes", "本次升级未附发行说明。")))
        notes_layout.addWidget(notes, 1)
        root.addWidget(notes_card, 1)

        assurance = QLabel("升级前自动备份，失败自动回滚。个人配置、音频库、声纹库、转录记录和已有识别模型保持不变。\n点击升级后，程序会关闭并自动启动新版，无需独立升级工具。")
        assurance.setObjectName("updateAssurance")
        assurance.setWordWrap(True)
        root.addWidget(assurance)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Yes)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("暂不升级")
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("一键升级并重启")
        buttons.button(QDialogButtonBox.StandardButton.Yes).setObjectName("primaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.setStyleSheet("""
            QDialog { background: #F3F0E8; color: #243E43; }
            QLabel#updateTitle { color: #173F4B; font-size: 24px; font-weight: 600; font-family: 'KaiTi', 'STKaiti', serif; }
            QLabel#updateSubtitle { color: #728078; font-size: 12px; }
            QLabel#updateVersion { color: #173F4B; background: #E8E2D5; border: 1px solid #D6CCBA; border-radius: 8px; padding: 12px; font-size: 25px; font-weight: 600; }
            QLabel#updateFacts { color: #6E756C; font-size: 12px; }
            QFrame#updateNotesCard { background: #FCFAF5; border: 1px solid #D9CFBD; border-radius: 10px; }
            QLabel#updateNotesTitle { color: #8B643E; font-size: 16px; font-weight: 600; font-family: 'KaiTi', 'STKaiti', serif; }
            QTextBrowser#updateNotes { background: transparent; border: none; color: #314A4D; font-size: 14px; line-height: 1.6; }
            QLabel#updateAssurance { color: #65736D; background: #E7EFEA; border-radius: 7px; padding: 10px; font-size: 12px; }
            QPushButton { min-height: 34px; padding: 0 18px; }
        """)

    @staticmethod
    def _notes_html(value: object) -> str:
        paragraphs = [line.strip() for line in str(value).splitlines() if line.strip()]
        if not paragraphs:
            paragraphs = ["本次升级未附发行说明。"]
        body = "".join(f"<p style='margin:0 0 10px 0'>{html.escape(line)}</p>" for line in paragraphs)
        return f"<div style='font-family:Microsoft YaHei, sans-serif'>{body}</div>"

    @property
    def package_path(self) -> Path:
        return Path(self.manifest["package_path"])
