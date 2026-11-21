from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "assets" / "guanhai-tingtao-logo-generated.png"
image = Image.open(source).convert("RGBA")
pixels = image.load()
for y in range(image.height):
    for x in range(image.width):
        red, green, blue, alpha = pixels[x, y]
        if max(red, green, blue) < 14:
            pixels[x, y] = (red, green, blue, 0)
for size in (512, 256, 64):
    resized = image.resize((size, size), Image.Resampling.LANCZOS)
    suffix = "" if size == 512 else f"-{size}"
    resized.save(ROOT / "assets" / f"guanhai-tingtao-logo{suffix}.png", optimize=True)
image.save(ROOT / "assets" / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("Guanhai Tingtao logo sizes and app.ico generated")
