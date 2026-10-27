"""Make the README previews in docs/images/ from the sprites, in Chinese and in English: girls.gif and
girls-en.gif (all six standing, animated: they take turns to talk and blink now and then, drawn from the face parts
by the app's own rules), moods-<girl>.png (each new girl's 8 moods; Claude's Chinese sheet is the hand-made
moods.png) and moods-<girl>-en.png (all six). Needs Microsoft YaHei (msyh.ttc, msyhbd.ttc).

    python devtools/make_previews.py [--fonts DIR]
"""
from __future__ import annotations

import argparse
import functools
import os
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from claude_pet.characters import CHARACTERS  # noqa: E402
from claude_pet.persona import MOODS  # noqa: E402
from claude_pet.pet_window import BLINK, MOUTH_CYCLE, MOUTH_FRAME  # noqa: E402  the app's own timing

OUT = ROOT / "docs" / "images"
TURN = 1200  # milliseconds each girl talks in the animated lineup, one after another
# Milliseconds after her turn begins that she blinks: with the turns 1200 apart, the twelve blinks of a loop fall
# every 600 ms, one girl at a time. They start 50 ms into a mouth step (150 ms), so no frame is shorter than
# MIN_FRAME: browsers play shorter GIF frames far slower.
BLINKS = (1700, 4700)
MIN_FRAME = 20
STEP = 10  # the timeline's resolution in milliseconds (a GIF's own unit)
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


@functools.lru_cache(maxsize=None)
def sprite(girl: str, mood: str, height: int, part: str | None = None) -> Image.Image:
    """Her sprite for this mood, or with `part` that face part (the same size as the sprite, so scaled alike).
    Cached for the animation's many frames: copy before drawing on it."""
    folder = ROOT / "assets" / ("sprites" if girl == "claude" else f"characters/{girl}")
    image = Image.open(folder / ("parts" if part else "") / f"{part or mood}.png").convert("RGBA")
    return image.resize((round(image.width * height / image.height), height), Image.LANCZOS)


def face(girl: str, ms: int) -> tuple[str, str | None, str | None]:
    """Her mood, mouth and eyes `ms` milliseconds into the loop: idle, then her turn to talk (the app's mouth
    cycle, resting closed), and a blink twice a loop (the app's blink)."""
    since = (ms - list(CHARACTERS).index(girl) * TURN) % (TURN * len(CHARACTERS))
    mood, mouth, eyes = "idle", None, None
    if since < TURN:
        mood = "talk"
        mouth = MOUTH_CYCLE[since // round(MOUTH_FRAME * 1000) % len(MOUTH_CYCLE)] or "mouth_closed"
    for start in BLINKS:
        eyes = eyes or next((part for until, part in BLINK if 0 <= since - start < round(until * 1000)), None)
    return mood, mouth, eyes


def face_parts(mood: str, mouth: str | None, eyes: str | None) -> list[str]:
    """The parts drawn over her sprite, in the app's order: the mouth first (talk covers its own open mouth with
    idle's closed one first), then the eyes (talk has its own blink)."""
    names = []
    if mouth:
        names += ["mouth_closed", mouth] if mood == "talk" and mouth != "mouth_closed" else [mouth]
    if eyes:
        names.append(f"talk_{eyes}" if mood == "talk" else eyes)
    return names


def timeline() -> list[tuple[dict[str, tuple[str, str | None, str | None]], int]]:
    """Every girl's face over one loop, as (faces, milliseconds) with each change starting a new frame."""
    frames: list[tuple[dict, int]] = []
    for ms in range(0, TURN * len(CHARACTERS), STEP):
        faces = {girl: face(girl, ms) for girl in CHARACTERS}
        if frames and frames[-1][0] == faces:
            frames[-1] = (faces, frames[-1][1] + STEP)
        else:
            frames.append((faces, STEP))
    return frames


def name(girl: str, lang: str) -> str:
    return CHARACTERS[girl].name if lang == "zh" else CHARACTERS[girl].name_en


def centred(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, size: int, fill, bold: bool = False) -> None:
    draw.text((x, y), text, font=font(size, bold), fill=fill, anchor="ma")


def save(image: Image.Image, filename: str) -> None:
    path = OUT / filename
    image.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


def lineup(lang: str, faces: dict[str, tuple[str, str | None, str | None]] | None = None) -> Image.Image:
    """All six standing, each with her face as given (default: idle, at rest)."""
    cell, height, top = 250, 320, 70
    canvas = Image.new("RGB", (cell * len(CHARACTERS), top + height + 110), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    centred(draw, canvas.width / 2, 16, TEXT[lang]["lineup"], 30, (60, 60, 60), bold=True)
    for i, (girl, c) in enumerate(CHARACTERS.items()):
        mood, mouth, eyes = (faces or {}).get(girl, ("idle", None, None))
        image = sprite(girl, mood, height).copy()
        for part in face_parts(mood, mouth, eyes):
            image.alpha_composite(sprite(girl, mood, height, part))
        canvas.paste(image, (i * cell + (cell - image.width) // 2, top), image)
        centred(draw, i * cell + cell / 2, top + height + 12, name(girl, lang), 24, c.theme.main, bold=True)
    centred(draw, canvas.width / 2, canvas.height - 34, TEXT[lang]["credit"], 15, GREY)
    return canvas


def palette(lang: str) -> Image.Image:
    """One palette for every frame, sampled from the lineup at rest and in each shape the loop shows, so the frames
    differ only where a face moves and the file stays small. Its last entry is the exact background."""
    shapes = (("talk", "mouth_open", None), ("talk", "mouth_half", None), ("idle", None, "eyes_closed"),
              ("idle", None, "eyes_half"))
    sheets = [lineup(lang), *(lineup(lang, dict.fromkeys(CHARACTERS, shape)) for shape in shapes)]
    sample = Image.new("RGB", (sheets[0].width, sheets[0].height * len(sheets)))
    for i, sheet in enumerate(sheets):
        sample.paste(sheet, (0, i * sheets[0].height))
    colours = sample.quantize(255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).getpalette()[:255 * 3]
    result = Image.new("P", (1, 1))
    result.putpalette(colours + [0] * (255 * 3 - len(colours)) + list(BACKGROUND))
    return result


def frame(lang: str, faces: dict[str, tuple[str, str | None, str | None]], colours: Image.Image) -> Image.Image:
    """One frame in the shared palette; the background is set to its own entry, as the nearest-colour search
    may pick a close one and leave a faint tint on a white page."""
    rgb = lineup(lang, faces)
    image = rgb.quantize(palette=colours, dither=Image.Dither.NONE)
    r, g, b = ImageChops.difference(rgb, Image.new("RGB", rgb.size, BACKGROUND)).split()
    image.paste(255, mask=ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v == 0 else 0))
    return image


def save_animated(lang: str, filename: str) -> None:
    """The lineup over one loop as a GIF that plays forever."""
    frames = timeline()
    colours = palette(lang)
    images = [frame(lang, faces, colours) for faces, _ in frames]
    path = OUT / filename
    images[0].save(path, save_all=True, append_images=images[1:], duration=[ms for _, ms in frames], loop=0,
                   optimize=False)
    print(f"wrote {path.relative_to(ROOT)} ({len(images)} frames, {path.stat().st_size // 1024} KB)")


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
    save_animated("zh", "girls.gif")
    save_animated("en", "girls-en.gif")
    for girl in CHARACTERS:
        if girl != "claude":
            save(moods(girl, "zh"), f"moods-{girl}.png")
        save(moods(girl, "en"), f"moods-{girl}-en.png")


if __name__ == "__main__":
    main()
