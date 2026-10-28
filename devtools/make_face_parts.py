"""Face overlay parts for the blink and talk animation (assets/sprites/parts/<part>.png).

The image model redraws the whole picture even for a "change only the eyes" edit, so only the eye or
mouth area of each generated edit is used: the pixels there that differ from idle, with soft edges,
become a transparent layer drawn over the sprite. "mouth_closed" is idle's own mouth, which closes the
open mouth of the talk sprite. Every part is cropped and scaled exactly like the sprites.

usage: python devtools/make_face_parts.py <raw_dir> <out_dir> [height] [--girl <id>]
  raw_dir:  the eight raw mood sheets, and parts/ with idle.png plus the generated edits
  out_dir:  assets/sprites/parts (Claude), or assets/characters/<id>/parts with --girl <id>
"""
from __future__ import annotations

import sys
from typing import NamedTuple
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from process_sprites import MOODS, crop_scale, load_raw, union_box  # noqa: E402
from claude_pet.sprites import PARTS  # noqa: E402  the part names the app loads

EYES = (360, 205, 655, 350)  # areas in the 1024 x 1024 raw canvas, with room for the soft edge
MOUTH = (440, 300, 565, 395)
FEATHER = 10  # pixels over which a part fades out at the edge of its area
MOUTH_KEEP = (466, 318, 538, 395)  # an eye part never touches the mouth: it is drawn over the mouth parts
EDITS = {"eyes_half": EYES, "eyes_closed": EYES, "mouth_half": MOUTH, "mouth_open": MOUTH, "mouth_o": MOUTH}


class Face(NamedTuple):
    """Where a girl's eyes and mouth are in her raw canvas: each a union of boxes (an eye box each for a tilted
    face), and the mouth area no eye part may touch."""
    eyes: tuple[tuple[int, int, int, int], ...]
    mouth: tuple[tuple[int, int, int, int], ...]
    keep: tuple[int, int, int, int]


FACES = {  # measured on each girl's eight raw expressions; Claude's are the constants above
    "claude": Face((EYES,), (MOUTH,), MOUTH_KEEP),
    "deepseek": Face(((400, 268, 512, 395), (528, 245, 635, 368)), ((478, 330, 588, 412),), (497, 352, 575, 400)),
    "gpt": Face(((365, 380, 500, 478), (515, 350, 642, 452)), ((465, 435, 570, 505),), (488, 450, 552, 497)),
    "gemini": Face(((400, 352, 512, 452), (525, 315, 645, 420)), ((483, 393, 578, 470),), (500, 405, 565, 460)),
    "qwen": Face(((385, 358, 515, 482), (545, 322, 662, 440)), ((488, 425, 598, 508),), (505, 438, 585, 495)),
    "glm": Face(((392, 322, 505, 440), (510, 305, 625, 412)), ((480, 390, 575, 472),), (497, 412, 565, 460)),
}


def boxes(face: Face, name: str) -> tuple[tuple[int, int, int, int], ...]:
    return face.eyes if name.startswith("eyes") else face.mouth
MOOD_EDITS = {  # parts/<mood>_<part>.png, edits of that expression's own raw sprite
    "happy": ("mouth_half", "mouth_open"),
    "think": ("mouth_half", "mouth_open", "eyes_half", "eyes_closed"),
    "panic": ("mouth_half", "mouth_open"),
    "angry": ("mouth_half", "mouth_open", "eyes_half", "eyes_closed"),
    "sad": ("mouth_half", "mouth_open", "eyes_half", "eyes_closed"),
}


def changed_mask(base: Image.Image, edit: Image.Image, box: tuple, keep_out: tuple[int, int, int, int] | None = None,
                 grow: int = 9) -> Image.Image:
    """The changed pixels inside `box` (one box, or a tuple of boxes), fading out towards its border. `keep_out`
    is an area left empty (the mouth, for an eye part); Claude's single EYES box keeps MOUTH_KEEP out by default.
    `grow`: the size (pixels, odd) of the square the changed pixels are widened by; the softening stays the same."""
    rects = box if isinstance(box[0], tuple) else (box,)
    if keep_out is None and box == EYES:
        keep_out = MOUTH_KEEP
    r, g, b = ImageChops.difference(edit.convert("RGB"), base.convert("RGB")).split()
    strongest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    area = Image.new("L", base.size, 0)
    for rect in rects:
        area.paste(255, rect)
    mask = ImageChops.multiply(strongest.point(lambda v: 255 if v > 30 else 0), area)
    mask = mask.filter(ImageFilter.MaxFilter(grow)).filter(ImageFilter.GaussianBlur(3))
    # The edit may have redrawn hair near the feature too: fade the area out towards its border, so no
    # straight seam shows where the patch ends.
    soft = Image.new("L", base.size, 0)
    for rect in rects:
        soft.paste(255, (rect[0] + FEATHER, rect[1] + FEATHER, rect[2] - FEATHER, rect[3] - FEATHER))
    soft = ImageChops.multiply(soft.filter(ImageFilter.GaussianBlur(FEATHER / 2)), area)
    if keep_out:
        keep = Image.new("L", base.size, 255)
        keep.paste(0, keep_out)
        soft = ImageChops.multiply(soft, keep.filter(ImageFilter.GaussianBlur(FEATHER / 2)))
    mask = ImageChops.multiply(ImageChops.multiply(mask, soft), base.getchannel("A"))
    if keep_out:
        mask.paste(0, keep_out)  # nothing of an eye part over the mouth, whatever the blur left there
    return mask


def part_mask(face: Face, base: Image.Image, edit: Image.Image, name: str, grow: int = 9, widen: int = 0
              ) -> Image.Image:
    """`widen`: the feature's boxes grown by this many pixels on every side (within the canvas)."""
    rects = tuple((max(0, x0 - widen), max(0, y0 - widen), min(base.width, x1 + widen), min(base.height, y1 + widen))
                  for x0, y0, x1, y1 in boxes(face, name))
    return changed_mask(base, edit, rects, face.keep if name.startswith("eyes") else None, grow)


# A panic mouth is a big wavy shape that reaches the edge of her mouth box, and its talking shapes are smaller:
# the old outline, where the box fades out, showed round them as a pale ring. So a new girl's panic mouth parts
# use a box this much wider and a mask widened further; Claude's accepted parts stay as they are.
PANIC_WIDEN = 20
PANIC_GROW = 21


def wide_panic_for(girl: str) -> bool:
    """Whose panic mouth parts are cut with the wider box: every girl's but Claude's (hers are accepted)."""
    return girl != "claude"


def layers(parts_dir: Path, talk: Image.Image | None = None, face: Face = FACES["claude"]) -> dict[str, Image.Image]:
    base = Image.open(parts_dir / "idle.png").convert("RGBA")
    out: dict[str, Image.Image] = {}
    masks = {}
    for name in EDITS:
        edit = Image.open(parts_dir / f"{name}.png").convert("RGBA").resize(base.size, Image.Resampling.LANCZOS)
        masks[name] = part_mask(face, base, edit, name)
        layer = edit.copy()
        layer.putalpha(masks[name])
        out[name] = layer
    closed = base.copy()
    cover = ImageChops.lighter(ImageChops.lighter(masks["mouth_half"], masks["mouth_open"]), masks["mouth_o"])
    if talk is not None:  # also all of the talk sprite's own open mouth, so none of it shows through
        cover = ImageChops.lighter(cover, part_mask(face, base, talk.resize(base.size, Image.Resampling.LANCZOS), "mouth"))
    closed.putalpha(cover)
    out["mouth_closed"] = closed
    if talk is not None:  # the talk sprite's eyes sit a little differently: its blink covers them as well
        talk_eyes = part_mask(face, base, talk.resize(base.size, Image.Resampling.LANCZOS), "eyes")
        for name in ("eyes_half", "eyes_closed"):
            layer = out[name].copy()
            layer.putalpha(ImageChops.lighter(masks[name], talk_eyes))
            out[f"talk_{name}"] = layer
    return out


def mood_layers(parts_dir: Path, images: dict[str, Image.Image], face: Face = FACES["claude"],
                moods: tuple[str, ...] | None = None, wide_panic: bool = False) -> dict[str, Image.Image]:
    """Each expression's own parts: the changed pixels against that expression's sprite, so its own
    mouth (or eyes) is covered by every shape made for it. `moods`: only these expressions (default all).
    `wide_panic`: panic's mouth parts cover past the old outline (PANIC_WIDEN); for the new girls."""
    out: dict[str, Image.Image] = {}
    for mood, names in MOOD_EDITS.items():
        base = images.get(mood)
        if base is None or (moods is not None and mood not in moods):
            continue
        for name in names:
            edit = Image.open(parts_dir / f"{mood}_{name}.png").convert("RGBA").resize(base.size, Image.Resampling.LANCZOS)
            layer = edit.copy()
            if wide_panic and mood == "panic" and name.startswith("mouth"):
                layer.putalpha(part_mask(face, base, edit, name, PANIC_GROW, PANIC_WIDEN))
            else:
                layer.putalpha(part_mask(face, base, edit, name))
            out[f"{mood}_{name}"] = layer
    return out


def ready_moods(raw_dir: Path) -> tuple[str, ...]:
    """The expressions whose edits are all there."""
    parts = raw_dir / "parts"
    return tuple(mood for mood, names in MOOD_EDITS.items() if all((parts / f"{mood}_{n}.png").is_file() for n in names))


def missing_sources(raw_dir: Path, whole: bool = True) -> list[Path]:
    """`whole` (Claude): every edit. Otherwise (a new girl): idle's, and each expression's all or none of them."""
    parts = raw_dir / "parts"
    needed = [raw_dir / f"{mood}.png" for mood in MOODS]  # all eight: they decide the common crop
    needed += [parts / "idle.png", *(parts / f"{name}.png" for name in EDITS)]
    for mood, names in MOOD_EDITS.items():
        started = any((parts / f"{mood}_{n}.png").is_file() for n in names)
        if whole or started:
            needed += [parts / f"{mood}_{name}.png" for name in names]
    return [path for path in needed if not path.is_file()]


def main(raw_dir: Path, out_dir: Path, height: int = 512, girl: str = "claude") -> int:
    missing = missing_sources(raw_dir, whole=girl == "claude")
    if missing:  # never a half-updated set: new sprites with stale parts would not match
        for path in missing:
            print(f"[missing] {path}")
        print("nothing written")
        return 1
    images = load_raw(raw_dir)
    union = union_box(images)
    out_dir.mkdir(parents=True, exist_ok=True)
    face = FACES[girl]
    moods = ready_moods(raw_dir)
    moody = mood_layers(raw_dir / "parts", images, face, moods, wide_panic=wide_panic_for(girl))
    every = {**layers(raw_dir / "parts", images.get("talk"), face), **moody}
    for name, layer in every.items():
        part = crop_scale(layer, union, height)
        part.save(out_dir / f"{name}.png", optimize=True)
        print(f"[ok] {name} {part.size}")
    # Then an expression whose parts are not made this time leaves none behind; only part files are touched,
    # so a mistyped out_dir (a sprites folder) keeps its sprites.
    for stale in out_dir.glob("*.png"):
        if stale.stem in PARTS and stale.stem not in every:
            stale.unlink()
            print(f"[removed] {stale.name}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    who = "claude"
    if "--girl" in args:
        i = args.index("--girl")
        who, args = (args[i + 1] if i + 1 < len(args) else ""), args[:i] + args[i + 2:]
    if len(args) < 2 or who not in FACES:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(args[0]), Path(args[1]), int(args[2]) if len(args) > 2 else 512, who))
