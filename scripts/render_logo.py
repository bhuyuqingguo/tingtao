from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
app = QGuiApplication([])
renderer = QSvgRenderer(str(ROOT / "assets" / "tinglan-logo.svg"))
if not renderer.isValid():
    raise RuntimeError("SVG logo could not be loaded")
for size, name in ((1024, "tinglan-logo.png"), (256, "tinglan-logo-256.png"), (64, "tinglan-logo-64.png")):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    if not image.save(str(ROOT / "assets" / name)):
        raise RuntimeError(f"Unable to save {name}")
    print(ROOT / "assets" / name)
