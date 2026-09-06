"""Generates desktop/icon.png: a dark tile with the app's one signature
flourish (the `$` prompt from the top-bar wordmark) in gold. Run once by
hand when the icon needs regenerating -- not part of install.sh, since the
output PNG is committed and doesn't need to be rebuilt on every install.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
BG = (20, 23, 28)  # --bg
BORDER = (231, 228, 221, 46)  # --border-strong, ~0.18 alpha on this bg
GOLD = (201, 161, 91)  # --gold
FONT_PATH = "/usr/share/fonts/TTF/JetBrainsMono-Bold.ttf"

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

radius = SIZE // 5
draw.rounded_rectangle(
    [0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=BG, outline=BORDER, width=4
)

font = ImageFont.truetype(FONT_PATH, int(SIZE * 0.52))
glyph = ">"
bbox = draw.textbbox((0, 0), glyph, font=font)
w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text(
    (SIZE / 2 - w / 2 - bbox[0], SIZE / 2 - h / 2 - bbox[1]),
    glyph,
    font=font,
    fill=GOLD,
)

out = Path(__file__).resolve().parent / "icon.png"
img.save(out)
print(f"wrote {out}")
