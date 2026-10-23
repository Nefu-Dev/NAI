# -*- coding: utf-8 -*-
"""Generate the NAI application icon (assets/nai.ico) with Pillow."""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "nai.ico")
SIZE = 256
BG = (22, 27, 34)          # dark slate
ACCENT = (217, 87, 71)     # terracotta (Claude-like)
GREEN = (96, 190, 120)     # NEFU green
FG = (240, 243, 246)


def font(size):
    for cand in [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf"]:
        if os.path.exists(cand):
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default()


def main():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = 52
    d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=r, fill=BG)
    # NEFU-green leaf accent bar
    d.rounded_rectangle([36, 178, 88, 200], radius=11, fill=GREEN)
    d.rounded_rectangle([88, 150, 104, 200], radius=8, fill=ACCENT)
    # "NAI" text
    f = font(120)
    d.text((128, 106), "NAI", font=f, fill=FG, anchor="mm")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    img.save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print("icon written:", OUT)


if __name__ == "__main__":
    main()
