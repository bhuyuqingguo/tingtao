from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(66)
        self._values = [0.0] * 80

    def set_values(self, values: list[float]) -> None:
        self._values = [max(0.0, min(1.0, float(value))) for value in values[-80:]] or [0.0]
        self.update()

    def clear(self) -> None:
        self.set_values([0.0] * 80)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F1EBDD"))
        center = self.height() / 2
        painter.setPen(QPen(QColor("#D7CBB5"), 1))
        painter.drawLine(8, int(center), self.width() - 8, int(center))
        count = max(1, len(self._values))
        step = (self.width() - 20) / count
        path = QPainterPath()
        for index, value in enumerate(self._values):
            x = 10 + index * step
            y = center - value * (self.height() / 2 - 8)
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        for index in range(count - 1, -1, -1):
            x = 10 + index * step
            path.lineTo(x, center + self._values[index] * (self.height() / 2 - 8))
        path.closeSubpath()
        painter.fillPath(path, QColor(43, 111, 111, 48))
        painter.setPen(QPen(QColor("#367C7A"), 1.6))
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
