from pathlib import Path
import shutil

from PySide6.QtWidgets import QApplication

from offline_transcriber.main_window import MainWindow


ROOT = Path(__file__).resolve().parents[1]
app = QApplication([])
window = MainWindow()
window.resize(1260, 880)
window.show()
window._set_source(str(ROOT / "assets" / "test-zh.wav"))
second = ROOT / "build-cache" / "test-zh-2.wav"
shutil.copy2(ROOT / "assets" / "test-zh.wav", second)
window._add_sources([str(second)])
app.processEvents()
for index, name in ((0, "guanhai-workspace.png"), (1, "guanhai-records.png"), (2, "guanhai-system.png")):
    window._show_page(index)
    app.processEvents()
    image = window.grab()
    if not image.save(str(ROOT / "build-cache" / name)):
        raise RuntimeError(f"Unable to save {name}")
window.theme_combo.setCurrentIndex(window.theme_combo.findData("modern"))
window._show_page(0)
app.processEvents()
window.grab().save(str(ROOT / "build-cache" / "guanhai-modern.png"))
window._update_launch_pending = True
window.close()
print("Guanhai Tingtao UI previews saved")
