from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class RecordingMiniWindow(QWidget):
    """Always-on-top meeting controls; recording stays in the main window."""

    restore_requested = Signal()
    marker_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setWindowTitle("观海·听涛 · 会中速记")
        self.setMinimumWidth(380)
        self.setStyleSheet("""
            QWidget { background: #FFFCF5; color: #243B3B; font-family: 'Microsoft YaHei UI'; }
            QLabel#timer { color: #B53C32; font-size: 22px; font-weight: 700; }
            QLabel#topic { color: #765022; font-size: 13px; }
            QPushButton { background: #FFFCF5; color: #243B3B; border: 1px solid #D8CBB4;
                          border-radius: 6px; padding: 7px 12px; }
            QPushButton#mark { background: #9A6B2F; color: white; border: none; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 11, 15, 11)
        row = QHBoxLayout()
        self.timer = QLabel("● 00:00")
        self.timer.setObjectName("timer")
        row.addWidget(self.timer)
        self.topic = QLabel("会议记录中 · 本地保存")
        self.topic.setObjectName("topic")
        row.addWidget(self.topic, 1)
        root.addLayout(row)
        controls = QHBoxLayout()
        marker = QPushButton("◆ 打点")
        marker.setObjectName("mark")
        marker.setToolTip("记录当前时间点，不改变正在识别的音频")
        marker.clicked.connect(self.marker_requested)
        controls.addWidget(marker)
        restore = QPushButton("返回完整窗口")
        restore.clicked.connect(self._restore)
        controls.addWidget(restore)
        root.addLayout(controls)

    def update_state(self, seconds: float, topic: str) -> None:
        minutes, secs = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        elapsed = f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
        self.timer.setText(f"● {elapsed}")
        self.topic.setText((topic.strip() or "会议记录中")[:32])

    def _restore(self) -> None:
        self.hide()
        self.restore_requested.emit()

    def closeEvent(self, event) -> None:
        # Closing the compact bar must never stop or discard an active recording.
        event.ignore()
        self._restore()
