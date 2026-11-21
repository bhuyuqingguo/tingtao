from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
image = Image.open(ROOT / "assets" / "tinglan-logo.png").convert("RGBA")
image.save(
    ROOT / "assets" / "app.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
