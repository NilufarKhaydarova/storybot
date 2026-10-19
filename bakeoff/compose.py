"""Lay the story text over a generated picture, the way the book page would look.

The picture is cropped to 2:1 (a square book opened flat), the text goes in a soft panel
on the side the prompt asked to keep calm, and a faint line marks the fold, so you can
see whether a face lands in it.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SPREAD_WIDTH = 2400
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def load_font(path: str | None, size: int) -> ImageFont.ImageFont:
    for candidate in [path, *FONT_CANDIDATES]:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def crop_to_ratio(img: Image.Image, ratio: float) -> Image.Image:
    w, h = img.size
    if w / h > ratio:
        new_w = round(h * ratio)
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    new_h = round(w / ratio)
    top = (h - new_h) // 2
    return img.crop((0, top, w, top + new_h))


def _wrap(text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if font.getlength(trial) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def spread(page: Path, text: str, side: str, out: Path, font_path: str | None = None) -> None:
    width, height = SPREAD_WIDTH, SPREAD_WIDTH // 2
    img = crop_to_ratio(Image.open(page).convert("RGB"), 2.0).resize((width, height), Image.LANCZOS)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font = load_font(font_path, 38)
    margin, pad = 90, 36
    box_w = width // 3 - 2 * margin
    lines = _wrap(text, font, box_w - 2 * pad)
    line_h = round(font.size * 1.4)
    left = margin if side == "left" else width - width // 3 + margin
    top = margin
    draw.rounded_rectangle((left, top, left + box_w, top + 2 * pad + line_h * len(lines)),
                           radius=28, fill=(255, 250, 238, 215))
    for i, line in enumerate(lines):
        draw.text((left + pad, top + pad + i * line_h), line, font=font, fill=(45, 32, 28, 255))
    draw.line((width // 2, 0, width // 2, height), fill=(255, 255, 255, 70), width=2)

    Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB").save(out, quality=90)
