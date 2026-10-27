"""Make the README previews in docs/images/ from the sprites, in Chinese and in English: girls.png and
girls-en.png (all six, standing), moods-<girl>.png (each new girl's 8 moods; Claude's Chinese sheet is the
hand-made moods.png) and moods-<girl>-en.png (all six). Needs Microsoft YaHei (msyh.ttc, msyhbd.ttc).

    python devtools/make_previews.py [--fonts DIR]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from claude_pet.characters import CHARACTERS  # noqa: E402
from claude_pet.persona import MOODS  # noqa: E402

OUT = ROOT / "docs" / "images"
FONT_FILES = ("msyh.ttc", "msyhbd.ttc")
BACKGROUND = (255, 255, 255)
GREY = (120, 120, 120)
TEXT = {
    "zh": {"lineup": "六位 AI 娘", "moods": "{name} · 8 种表情", "credit": "AI 生成，角色原设 ZipZipPipe · 仅限非商用",
           "idle": "待机", "talk": "说话", "happy": "开心", "think": "思考",
           "panic": "慌张", "angry": "生气", "sad": "难过", "sleep": "睡觉"},
    "en": {"lineup": "Six AI girls", "moods": "{name} · 8 moods",
           "credit": "AI-generated after designs by ZipZipPipe · non-commercial use only",
           "idle": "Idle", "talk": "Talking", "happy": "Happy", "think": "Thinking",
           "panic": "Panicking", "angry": "Angry", "sad": "Sad", "sleep": "Sleeping"},
}
fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(fonts / FONT_FILES[bold]), size)


def sprite(girl: str, mood: str, height: int) -> Image.Image:
    folder = ROOT / "assets" / ("sprites" if girl == "claude" else f"characters/{girl}")
    image = Image.open(folder / f"{mood}.png").convert("RGBA")
    return image.resize((round(image.width * height / image.height), height), Image.LANCZOS)


def name(girl: str, lang: str) -> str:
    return CHARACTERS[girl].name if lang == "zh" else CHARACTERS[girl].name_en


def centred(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, size: int, fill, bold: bool = False) -> None:
    draw.text((x, y), text, font=font(size, bold), fill=fill, anchor="ma")


def save(image: Image.Image, filename: str) -> None:
    path = OUT / filename
    image.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


def lineup(lang: str) -> Image.Image:
    cell, height, top = 250, 320, 70
    canvas = Image.new("RGB", (cell * len(CHARACTERS), top + height + 110), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    centred(draw, canvas.width / 2, 16, TEXT[lang]["lineup"], 30, (60, 60, 60), bold=True)
    for i, (girl, c) in enumerate(CHARACTERS.items()):
        image = sprite(girl, "idle", height)
        canvas.paste(image, (i * cell + (cell - image.width) // 2, top), image)
        centred(draw, i * cell + cell / 2, top + height + 12, name(girl, lang), 24, c.theme.main, bold=True)
    centred(draw, canvas.width / 2, canvas.height - 34, TEXT[lang]["credit"], 15, GREY)
    return canvas


def moods(girl: str, lang: str) -> Image.Image:
    theme = CHARACTERS[girl].theme
    cell, height, top, row = 250, 290, 70, 345
    canvas = Image.new("RGB", (cell * 4, top + row * 2 + 40), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    centred(draw, canvas.width / 2, 16, TEXT[lang]["moods"].format(name=name(girl, lang)), 30, theme.deep, bold=True)
    for i, mood in enumerate(MOODS):
        x, y = (i % 4) * cell, top + (i // 4) * row
        image = sprite(girl, mood, height)
        canvas.paste(image, (x + (cell - image.width) // 2, y), image)
        centred(draw, x + cell / 2, y + height + 6, TEXT[lang][mood], 20, theme.main)
    centred(draw, canvas.width / 2, canvas.height - 34, TEXT[lang]["credit"], 15, GREY)
    return canvas


def main() -> None:
    global fonts
    parser = argparse.ArgumentParser()
    parser.add_argument("--fonts", type=Path, help=f"folder with {' and '.join(FONT_FILES)} (default: the Windows fonts)")
    args = parser.parse_args()
    fonts = args.fonts or fonts
    missing = [f for f in FONT_FILES if not (fonts / f).is_file()]
    if missing:
        sys.exit(f"{', '.join(missing)} not found in {fonts}; pass --fonts with the folder that has Microsoft YaHei")
    save(lineup("zh"), "girls.png")
    save(lineup("en"), "girls-en.png")
    for girl in CHARACTERS:
        if girl != "claude":
            save(moods(girl, "zh"), f"moods-{girl}.png")
        save(moods(girl, "en"), f"moods-{girl}-en.png")


if __name__ == "__main__":
    main()
