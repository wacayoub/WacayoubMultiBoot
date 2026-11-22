"""Draws src/WMultiBoot/plugin.png (100x40, plugin browser icon)."""
import os
from PIL import Image, ImageDraw, ImageFont

here = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(here, "..", "src", "WMultiBoot", "plugin.png")
W, H, K = 100, 40, 4
im = Image.new("RGBA", (W * K, H * K), (11, 16, 32, 255))
d = ImageDraw.Draw(im)
d.rounded_rectangle([0, 0, W * K - 1, H * K - 1], radius=8 * K, fill=(19, 26, 46, 255))
# three stacked slots, middle one active
for i, col in enumerate([(38, 50, 79), (34, 211, 238), (38, 50, 79)]):
    y = (7 + i * 9) * K
    d.rounded_rectangle([8 * K, y, 34 * K, y + 7 * K], radius=2 * K, fill=col)
d.ellipse([29 * K, 19 * K, 32 * K, 22 * K], fill=(255, 255, 255))
try:
    f = ImageFont.truetype("arialbd.ttf", 15 * K)
    f2 = ImageFont.truetype("arial.ttf", 9 * K)
except Exception:
    f = f2 = ImageFont.load_default()
d.text((41 * K, 4 * K), "Multi", font=f, fill=(232, 237, 245))
d.text((41 * K, 22 * K), "BOOT", font=f2, fill=(34, 211, 238))
im = im.resize((W, H), Image.LANCZOS)
im.save(out)
print(out)
