from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class WaveformWidget(QWidget):
    """A right-aligned, continuously scrolling history of the last 60 seconds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(118)
        self._values = deque(maxlen=1200)  # 50 ms recorder updates × 60 seconds

    def append_peak(self, value: float) -> None:
        self._values.append(max(0.0, min(1.0, float(value))))
        self.update()

    def set_values(self, values: list[float]) -> None:
        self._values.clear()
        for value in values[-1200:]:
            self._values.append(max(0.0, min(1.0, float(value))))
        self.update()

    def clear(self) -> None:
        self.set_values([])

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F6F0E4"))
        left, right, top, bottom = 16.0, self.width() - 16.0, 28.0, self.height() - 24.0
        center = (top + bottom) / 2
        width = right - left
        painter.setFont(self.font())
        painter.setPen(QColor("#6F766B"))
        painter.drawText(QRectF(left, 5, 240, 18), Qt.AlignmentFlag.AlignLeft, "近 60 秒历史波形")
        painter.drawText(QRectF(right - 110, 5, 110, 18), Qt.AlignmentFlag.AlignRight, "最新 →")
        painter.setPen(QPen(QColor("#DED3BF"), 1))
        for index in range(5):
            x = left + width * index / 4
            painter.drawLine(int(x), int(top), int(x), int(bottom))
            label = "现在" if index == 4 else f"−{60 - index * 15}s"
            painter.drawText(QRectF(x - 28, bottom + 3, 56, 17), Qt.AlignmentFlag.AlignCenter, label)
        painter.drawLine(int(left), int(center), int(right), int(center))
        values = list(self._values)
        columns = min(240, max(1, int(width / 3)))
        peaks = []
        for column in range(columns):
            start = column * len(values) // columns
            end = (column + 1) * len(values) // columns
            peaks.append(max(values[start:end], default=0.0))
        step = width / columns
        path = QPainterPath()
        for index, value in enumerate(peaks):
            x = right - (len(peaks) - index) * step + step / 2
            amplitude = max(0.7, value * (bottom - top) / 2)
            path.moveTo(x, center - amplitude)
            path.lineTo(x, center + amplitude)
        painter.setPen(QPen(QColor("#327C78"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(path)


class LevelMeter(QWidget):
    """Peak meter: green below -12 dB, amber to -6 dB, red to 0 dB."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(66)
        self.setMaximumWidth(310)
        self._level = 0.0

    def set_level(self, value: float) -> None:
        self._level = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        left, right, top, bottom = 10.0, width - 10.0, 25.0, height - 12.0
        painter.fillRect(QRectF(left, top, right - left, bottom - top), QColor("#DDD5C5"))
        db = -60.0 if self._level <= 0 else max(-60.0, 20 * math.log10(self._level))
        normalized = max(0.0, min(1.0, (db + 36) / 36))
        segments = 36
        active = round(normalized * segments)
        gap = 2.0
        segment_width = (right - left - gap * (segments - 1)) / segments
        for index in range(segments):
            position = (index + 1) / segments
            segment_db = -36 + position * 36
            color = QColor("#D85245") if segment_db > -6 else QColor("#D5A83E") if segment_db > -12 else QColor("#3D9173")
            if index >= active:
                color = QColor("#E4DED1")
            painter.fillRect(QRectF(left + index * (segment_width + gap), top, segment_width, bottom - top), color)
        painter.setFont(self.font())
        painter.setPen(QColor("#756E61"))
        for label, x, alignment in (("-12 dB", left + (right - left) * 2 / 3, Qt.AlignmentFlag.AlignCenter),
                                    ("-6 dB", left + (right - left) * 5 / 6, Qt.AlignmentFlag.AlignCenter)):
            painter.drawText(QRectF(x - 26, 2, 52, 18), alignment, label)
        painter.drawText(QRectF(right - 52, 2, 52, 18), Qt.AlignmentFlag.AlignRight, "0 dB")
        painter.drawText(QRectF(left, bottom + 1, right - left, 12), Qt.AlignmentFlag.AlignRight, f"峰值 {db:.1f} dB" if self._level else "等待声音")


class LogoTally(QWidget):
    """The seal-sun in the logo becomes a gentle cinnabar recording tally."""

    def __init__(self, logo_path, parent=None):
        super().__init__(parent)
        self.logo = QPixmap(str(logo_path))
        self.setFixedSize(52, 52)
        self._recording = False
        self._phase = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._breathe)

    def set_recording(self, active: bool) -> None:
        self._recording = active
        self._phase = 0.0
        if active:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def _breathe(self) -> None:
        self._phase = (self._phase + 0.055) % (2 * math.pi)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(self.rect(), self.logo)
        scale = min(self.width(), self.height()) / 256
        center_x, center_y = 189 * scale, 56 * scale
        if not self._recording:
            return
        pulse = (math.sin(self._phase) + 1) / 2
        glow = QRadialGradient(center_x, center_y, (26 + 6 * pulse) * scale)
        glow.setColorAt(0, QColor(255, 68, 46, round(40 + 110 * pulse)))
        glow.setColorAt(0.52, QColor(242, 46, 32, round(20 + 90 * pulse)))
        glow.setColorAt(1, QColor(223, 35, 26, 0))
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(center_x - 36 * scale), int(center_y - 36 * scale),
                            int(72 * scale), int(72 * scale))
        sun = QRadialGradient(center_x - 3 * scale, center_y - 4 * scale, 16 * scale)
        sun.setColorAt(0, QColor(255, 117 + round(45 * pulse), 77))
        sun.setColorAt(0.55, QColor(246, 55 + round(15 * pulse), 36))
        sun.setColorAt(1, QColor(200, 29, 24))
        painter.setBrush(sun)
        painter.setPen(QPen(QColor(148, 40, 31, 190), max(0.7, scale)))
        painter.setOpacity(pulse)
        painter.drawEllipse(int(center_x - 14 * scale), int(center_y - 14 * scale),
                            int(28 * scale), int(28 * scale))
        painter.setOpacity(1)
        border = QColor(15, 54, 69) if pulse < 0.5 else QColor(233, 49, 36)
        border.setAlpha(round(100 + 155 * abs(pulse - 0.5) * 2))
        painter.setPen(QPen(border, max(1.5, 7 * scale)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(14 * scale, 14 * scale, 228 * scale, 228 * scale),
                                38 * scale, 38 * scale)


class RecordingBorder(QWidget):
    """Mouse-transparent tally light drawn above the whole main window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._recording = False
        self._bright = True
        self.timer = QTimer(self)
        self.timer.setInterval(620)
        self.timer.timeout.connect(self._blink)

    def set_recording(self, active: bool) -> None:
        self._recording = active
        self._bright = True
        if active:
            self.resize(self.parentWidget().size())
            self.show()
            self.raise_()
            self.timer.start()
        else:
            self.timer.stop()
            self.hide()
        self.update()

    def _blink(self) -> None:
        self._bright = not self._bright
        self.update()

    def paintEvent(self, event) -> None:
        del event
        if not self._recording:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = 245 if self._bright else 95
        painter.setPen(QPen(QColor(220, 59, 49, alpha), 5))
        painter.drawRoundedRect(QRectF(3, 3, self.width() - 6, self.height() - 6), 4, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(211, 49, 43, alpha))
        painter.drawRoundedRect(QRectF(self.width() - 176, 14, 158, 34), 7, 7)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(self.width() - 176, 14, 158, 34), Qt.AlignmentFlag.AlignCenter, "●  录音中  REC")
