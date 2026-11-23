from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .paths import APP_ROOT


class OceanSplash(QWidget):
    """A short, fully local opening scene; no media or network is fetched."""

    finished = Signal()

    def __init__(self, logo_path, duration_ms: int = 3000):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(660, 400)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击进入")
        self._elapsed = 0
        self._duration = max(100, duration_ms)
        self._closed = False
        self._phase = 0.0
        self.logo = QPixmap(str(logo_path)) if logo_path.is_file() else QPixmap()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 44, 48, 32)
        layout.addStretch(1)
        self.title = QLabel("观海 · 听涛")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setFont(QFont("STKaiti", 34, QFont.Weight.Bold))
        self.title.setStyleSheet("color: #F7EFDA; background: transparent;")
        layout.addWidget(self.title)
        subtitle = QLabel("观海听涛，声落成章")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #D9CDAE; font-size: 15px; letter-spacing: 4px; background: transparent;")
        layout.addWidget(subtitle)
        layout.addSpacing(18)
        self.status = QLabel("潮声初起 · 正在准备本地声音空间")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color: #B8CCC5; font-size: 11px; background: transparent;")
        layout.addWidget(self.status)
        layout.addStretch(2)
        hint = QLabel("本地离线 · 点击跳过")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #90AEA8; font-size: 10px; background: transparent;")
        layout.addWidget(hint)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.sound = QSoundEffect(self)
        self.sound.setSource(QUrl.fromLocalFile(str(APP_ROOT / "assets" / "ocean-intro.wav")))
        self.sound.setVolume(0.42)
        self.sound.play()

    def _tick(self) -> None:
        self._elapsed += self.timer.interval()
        self._phase += 0.045
        self.update()
        if self._elapsed >= self._duration:
            self.finish()

    def finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.sound.stop()
        self.finished.emit()
        self.close()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.finish()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Space):
            self.finish()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor("#102F37"))
        gradient.setColorAt(0.55, QColor("#1E4C51"))
        gradient.setColorAt(1, QColor("#0B262E"))
        painter.fillRect(self.rect(), gradient)
        painter.setPen(QPen(QColor(186, 157, 100, 120), 1))
        painter.drawRoundedRect(QRectF(12, 12, self.width() - 24, self.height() - 24), 10, 10)
        if not self.logo.isNull():
            logo = self.logo.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width() - logo.width()) // 2, 42, logo)
        # Three quiet wave bands animate independently behind the typography.
        for band, (baseline, color) in enumerate(((274, QColor(118, 179, 172, 70)), (296, QColor(180, 200, 178, 90)), (320, QColor(93, 145, 146, 100)))):
            path = QPainterPath()
            path.moveTo(0, self.height())
            path.lineTo(0, baseline)
            for x in range(self.width() + 8, 8):
                y = baseline + math.sin(x * 0.018 + self._phase + band * 1.6) * (8 + band * 2)
                y += math.sin(x * 0.035 - self._phase * 0.7) * 3
                path.lineTo(x, y)
            path.lineTo(self.width(), self.height())
            path.closeSubpath()
            painter.fillPath(path, color)
        painter.setPen(QPen(QColor(216, 198, 151, 140), 1.4))
        path = QPainterPath()
        for x in range(150, 511, 4):
            envelope = math.sin((x - 150) / 360 * math.pi)
            y = 346 + math.sin(x * 0.095 + self._phase * 2) * 6 * envelope
            if x == 150:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.drawPath(path)
