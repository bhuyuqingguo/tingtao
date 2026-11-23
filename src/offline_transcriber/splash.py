from __future__ import annotations

import math
import random

from PySide6.QtCore import QRectF, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QWidget

from .paths import APP_ROOT


SCENES = (
    ("潮生", "观海听涛，声落成章", "#102F37", "#1E4C51", "#0B262E"),
    ("远山", "潮起有声，落笔成文", "#243D40", "#52665D", "#172E34"),
    ("听涛", "海纳千言，涛声入卷", "#203D48", "#386568", "#102C38"),
    ("星夜", "静听山海，文字自生", "#172A3B", "#284653", "#101E2D"),
)


class OceanSplash(QWidget):
    """A short, fully local opening scene with varied classical compositions."""

    finished = Signal()

    def __init__(self, logo_path, duration_ms: int = 3000, scene_index: int | None = None):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(660, 400)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击进入")
        self._elapsed = 0
        self._duration = max(100, duration_ms)
        self._closed = False
        self._phase = 0.0
        self.scene_index = random.SystemRandom().randrange(len(SCENES)) if scene_index is None else scene_index % len(SCENES)
        self.scene_name, self.poetry, *_ = SCENES[self.scene_index]
        self.logo = QPixmap(str(logo_path)) if logo_path.is_file() else QPixmap()
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

    def _text(self, painter: QPainter, rect: QRectF, text: str, size: int, color: str,
              family: str = "Microsoft YaHei UI", weight: QFont.Weight = QFont.Weight.Normal) -> None:
        painter.setFont(QFont(family, size, weight))
        painter.setPen(QColor(color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _waves(self, painter: QPainter, baselines: tuple[int, ...]) -> None:
        colors = (QColor(118, 179, 172, 58), QColor(180, 200, 178, 75), QColor(93, 145, 146, 96))
        for band, baseline in enumerate(baselines):
            path = QPainterPath()
            path.moveTo(0, self.height())
            path.lineTo(0, baseline)
            for x in range(self.width() + 8, 8):
                y = baseline + math.sin(x * 0.018 + self._phase + band * 1.6) * (7 + band * 2)
                y += math.sin(x * 0.035 - self._phase * 0.7) * 3
                path.lineTo(x, y)
            path.lineTo(self.width(), self.height())
            path.closeSubpath()
            painter.fillPath(path, colors[band])

    def _paint_scene(self, painter: QPainter) -> None:
        if self.scene_index == 1:
            # Sparse ink-wash mountain silhouettes behind the quiet sea.
            for offset, color in ((0, QColor(16, 46, 50, 105)), (34, QColor(31, 59, 58, 115))):
                path = QPainterPath()
                path.moveTo(0, 310)
                for x, y in ((0, 242), (75, 192 + offset), (133, 234), (230, 156 + offset),
                             (320, 238), (410, 185 + offset), (500, 242), (590, 202 + offset), (660, 250)):
                    path.lineTo(x, y)
                path.lineTo(660, 340)
                path.lineTo(0, 340)
                painter.fillPath(path, color)
        elif self.scene_index == 2:
            painter.setPen(QPen(QColor(215, 189, 126, 65), 1))
            for radius in (105, 121, 137):
                painter.drawEllipse(QRectF(330 - radius, 91 - radius, radius * 2, radius * 2))
            painter.setPen(QPen(QColor(193, 159, 96, 85), 1.2))
            painter.drawLine(86, 289, 574, 289)
        elif self.scene_index == 3:
            for index in range(27):
                x = (index * 89 + 37) % 610 + 25
                y = (index * 47 + 23) % 264 + 16
                radius = 1.4 if index % 5 == 0 else 0.7
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(233, 216, 165, 95 + (index % 3) * 35))
                painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))
            painter.setBrush(QColor(220, 188, 115, 150))
            painter.drawEllipse(QRectF(568, 34, 24, 24))
        self._waves(painter, (307, 330, 352))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _, _, top, middle, bottom = SCENES[self.scene_index]
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor(top))
        gradient.setColorAt(0.58, QColor(middle))
        gradient.setColorAt(1, QColor(bottom))
        painter.fillRect(self.rect(), gradient)
        self._paint_scene(painter)
        painter.setPen(QPen(QColor(198, 168, 108, 145), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(12, 12, self.width() - 24, self.height() - 24), 10, 10)
        if not self.logo.isNull():
            logo = self.logo.scaled(82, 82, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width() - logo.width()) // 2, 38, logo)
        # Fixed, non-overlapping typographic bands: 38–120, 142–192, 208–234, 256–278, 365–383.
        self._text(painter, QRectF(48, 142, 564, 50), "观海 · 听涛", 34, "#F7EFDA", "STKaiti", QFont.Weight.Bold)
        self._text(painter, QRectF(48, 208, 564, 26), self.poetry, 14, "#E2D6B9", "STKaiti")
        self._text(painter, QRectF(48, 256, 564, 22), f"{self.scene_name} · 正在准备本地声音空间", 10, "#C5D4CB")
        self._text(painter, QRectF(48, 365, 564, 18), "本地离线 · 点击跳过", 9, "#ADC2BA")
