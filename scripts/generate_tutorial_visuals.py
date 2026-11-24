"""Generate twelve original workflow diagrams and real application screenshots."""
from __future__ import annotations

import math
import shutil
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from offline_transcriber.main_window import MainWindow
from offline_transcriber.transcriber import SegmentData, TranscriptionResult
from offline_transcriber.tutorial_content import TUTORIAL_VISUALS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "tutorial"
PREVIEW = ROOT / "build-cache" / "tutorial-visuals"


def diagram(number: int, title: str, steps: tuple[str, ...], note: str) -> QImage:
    image = QImage(1200, 440, QImage.Format.Format_ARGB32)
    image.fill(QColor("#F7F3E9"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#8B643E"))
    painter.setFont(QFont("KaiTi", 27, QFont.Weight.Bold))
    painter.drawText(QRect(48, 24, 1100, 54), Qt.AlignmentFlag.AlignLeft, f"{number:02d}  {title}")
    painter.setPen(QPen(QColor("#D8C9AA"), 2))
    painter.drawLine(48, 88, 1152, 88)
    for index, step in enumerate(steps):
        x = 50 + index * 285
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#CDBD9F"), 2))
        painter.drawRoundedRect(x, 120, 250, 188, 18, 18)
        painter.setBrush(QColor("#2E6F73"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(x + 92, 137, 66, 66)
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Microsoft YaHei", 21, QFont.Weight.Bold))
        painter.drawText(QRect(x + 92, 137, 66, 66), Qt.AlignmentFlag.AlignCenter, str(index + 1))
        painter.setPen(QColor("#29474A"))
        painter.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.DemiBold))
        painter.drawText(QRect(x + 18, 216, 214, 74), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, step)
        if index < 3:
            painter.setPen(QPen(QColor("#9B784C"), 4))
            painter.drawLine(x + 256, 214, x + 278, 214)
            painter.drawLine(x + 270, 206, x + 278, 214)
            painter.drawLine(x + 270, 222, x + 278, 214)
    painter.setBrush(QColor("#EEE5D3"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(50, 336, 1100, 64, 12, 12)
    painter.setPen(QColor("#725536"))
    painter.setFont(QFont("Microsoft YaHei", 14))
    painter.drawText(QRect(72, 344, 1056, 48), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, f"要点：{note}")
    painter.end()
    return image


def save_screenshots(app: QApplication) -> None:
    window = MainWindow()
    window.resize(1360, 920)
    window.show()
    sample = ROOT / "assets" / "test-zh.wav"
    second = ROOT / "build-cache" / "tutorial-second.wav"
    shutil.copy2(sample, second)
    for chapter in TUTORIAL_VISUALS.values():
        number = chapter["number"]
        page = chapter["page"]
        window._show_page(page)
        window._set_recording_tally(False)
        if number == 1:
            window._set_source(str(sample))
            window.hotwords_edit.setText("观海听涛，银河麒麟，量子通信")
        elif number == 2:
            window._add_sources([str(sample), str(second)])
        elif number == 4:
            history = [abs(math.sin(i / 29)) * (0.18 + 0.58 * abs(math.sin(i / 173))) for i in range(1200)]
            window.audio_panel.waveform.set_values(history)
            window.audio_panel.level.set_level(0.42)
            window.audio_panel.meeting_panel.topic.setText("离线部署方案评审会")
            window.audio_panel.meeting_panel.markers = [
                {"seconds": 8.0, "type": "重点", "note": "先验证短音频"},
                {"seconds": 26.0, "type": "待办", "note": "复核专业术语"},
            ]
            window.audio_panel.meeting_panel._refresh_markers()
            window._set_recording_tally(True)
            window.logo_tally._phase = math.pi / 2
        elif number == 6:
            window._set_source(str(sample))
            sample_result = TranscriptionResult(
                source=str(sample), model="轻量模型", language="zh", language_probability=1.0,
                duration=24, created_at="教学示例", sources=(str(sample),),
                segments=(
                    SegmentData(0, 7, "今天讨论离线转录部署安排。", speaker="主持人"),
                    SegmentData(8, 15, "请核对决定事项、责任人和完成日期。", speaker="记录人"),
                    SegmentData(16, 23, "导出前复核姓名、数字与专业术语。", speaker="主持人"),
                ),
            )
            window.review_panel.set_result(sample_result)
            window.tabs.setCurrentIndex(1)
        elif number == 7:
            window.speaker_check.setChecked(True)
        elif number == 8:
            window.text_edit.setPlainText("今天讨论离线部署安排。决定先验证短音频，再处理长会议。")
            window.minutes_edit.setPlainText("会议重点\n• 先验证短音频，再处理长会议。\n\n决定事项\n• 使用本地离线流程，不上传原文。\n\n待办事项\n• 复核转录中的姓名、数字与专业术语。")
            window.tabs.setCurrentIndex(2)
        if number != 7:
            window.speaker_check.setChecked(False)
        if number not in {6, 8}:
            window.tabs.setCurrentIndex(0)
        app.processEvents()
        # Chapter four includes the complete window to show the classical TALLY logo and red border.
        pixmap = window.grab() if number == 4 else window.stack.currentWidget().grab()
        image = pixmap.toImage().scaledToWidth(1200, Qt.TransformationMode.SmoothTransformation)
        if not image.save(str(OUT / f"screen-{number:02d}.png")):
            raise RuntimeError(f"Could not save screenshot {number}")
    window._set_recording_tally(False)
    window._update_launch_pending = True
    window.close()
    second.unlink(missing_ok=True)


def contact_sheet(images: list[QImage]) -> None:
    sheet = QImage(1200, 6 * 250, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#E9E2D4"))
    painter = QPainter(sheet)
    for index, image in enumerate(images):
        target = QRect((index % 2) * 600, (index // 2) * 250, 590, 240)
        painter.drawImage(target, image)
    painter.end()
    sheet.save(str(PREVIEW / "diagrams-overview.png"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    images = []
    for number, item in TUTORIAL_VISUALS.items():
        image = diagram(number, item["title"], item["steps"], item["note"])
        if not image.save(str(OUT / f"diagram-{number:02d}.png")):
            raise RuntimeError(f"Could not save diagram {number}")
        images.append(image)
    save_screenshots(app)
    contact_sheet(images)
    print(f"Generated 12 diagrams and 12 real UI screenshots: {OUT}")
    print(f"Visual overview: {PREVIEW / 'diagrams-overview.png'}")


if __name__ == "__main__":
    main()
