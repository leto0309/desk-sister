"""Face overlay parts for the blink and talk animation (assets/sprites/parts/<part>.png).

The image model redraws the whole picture even for a "change only the eyes" edit, so only the eye or
mouth area of each generated edit is used: the pixels there that differ from idle, with soft edges,
become a transparent layer drawn over the sprite. "mouth_closed" is idle's own mouth, which closes the
open mouth of the talk sprite. Every part is cropped and scaled exactly like the sprites.

usage: python devtools/make_face_parts.py <raw_dir> <out_dir> [height]
  raw_dir:  the eight raw mood sheets, and parts/ with idle.png plus the generated edits
  out_dir:  assets/sprites/parts
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_sprites import MOODS, crop_scale, load_raw, union_box  # noqa: E402

EYES = (360, 205, 655, 350)  # areas in the 1024 x 1024 raw canvas, with room for the soft edge
MOUTH = (440, 300, 565, 395)
FEATHER = 10  # pixels over which a part fades out at the edge of its area
MOUTH_KEEP = (466, 318, 538, 395)  # an eye part never touches the mouth: it is drawn over the mouth parts
EDITS = {"eyes_half": EYES, "eyes_closed": EYES, "mouth_half": MOUTH, "mouth_open": MOUTH, "mouth_o": MOUTH}
MOOD_EDITS = {  # parts/<mood>_<part>.png, edits of that expression's own raw sprite
    "happy": ("mouth_half", "mouth_open"),
    "think": ("mouth_half", "mouth_open", "eyes_half", "eyes_closed"),
    "panic": ("mouth_half", "mouth_open"),
    "angry": ("mouth_half", "mouth_open", "eyes_half", "eyes_closed"),
    "sad": ("mouth_half", "mouth_open", "eyes_half", "eyes_closed"),
}


def changed_mask(base: Image.Image, edit: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    r, g, b = ImageChops.difference(edit.convert("RGB"), base.convert("RGB")).split()
    strongest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    area = Image.new("L", base.size, 0)
    area.paste(255, box)
    mask = ImageChops.multiply(strongest.point(lambda v: 255 if v > 30 else 0), area)
    mask = mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
    # The edit may have redrawn hair near the feature too: fade the area out towards its border, so no
    # straight seam shows where the patch ends.
    soft = Image.new("L", base.size, 0)
    soft.paste(255, (box[0] + FEATHER, box[1] + FEATHER, box[2] - FEATHER, box[3] - FEATHER))
    soft = ImageChops.multiply(soft.filter(ImageFilter.GaussianBlur(FEATHER / 2)), area)
    if box == EYES:
        keep = Image.new("L", base.size, 255)
        keep.paste(0, MOUTH_KEEP)
        soft = ImageChops.multiply(soft, keep.filter(ImageFilter.GaussianBlur(FEATHER / 2)))
    mask = ImageChops.multiply(ImageChops.multiply(mask, soft), base.getchannel("A"))
    if box == EYES:
        mask.paste(0, MOUTH_KEEP)  # nothing of an eye part over the mouth, whatever the blur left there
    return mask


def layers(parts_dir: Path, talk: Image.Image | None = None) -> dict[str, Image.Image]:
    base = Image.open(parts_dir / "idle.png").convert("RGBA")
    out: dict[str, Image.Image] = {}
    masks = {}
    for name, box in EDITS.items():
        edit = Image.open(parts_dir / f"{name}.png").convert("RGBA").resize(base.size, Image.Resampling.LANCZOS)
        masks[name] = changed_mask(base, edit, box)
        layer = edit.copy()
        layer.putalpha(masks[name])
        out[name] = layer
    closed = base.copy()
    cover = ImageChops.lighter(ImageChops.lighter(masks["mouth_half"], masks["mouth_open"]), masks["mouth_o"])
    if talk is not None:  # also all of the talk sprite's own open mouth, so none of it shows through
        cover = ImageChops.lighter(cover, changed_mask(base, talk.resize(base.size, Image.Resampling.LANCZOS), MOUTH))
    closed.putalpha(cover)
    out["mouth_closed"] = closed
    if talk is not None:  # the talk sprite's eyes sit a little differently: its blink covers them as well
        talk_eyes = changed_mask(base, talk.resize(base.size, Image.Resampling.LANCZOS), EYES)
        for name in ("eyes_half", "eyes_closed"):
            layer = out[name].copy()
            layer.putalpha(ImageChops.lighter(masks[name], talk_eyes))
            out[f"talk_{name}"] = layer
    return out


def mood_layers(parts_dir: Path, images: dict[str, Image.Image]) -> dict[str, Image.Image]:
    """Each expression's own parts: the changed pixels against that expression's sprite, so its own
    mouth (or eyes) is covered by every shape made for it."""
    out: dict[str, Image.Image] = {}
    for mood, names in MOOD_EDITS.items():
        base = images.get(mood)
        if base is None:
            continue
        for name in names:
            edit = Image.open(parts_dir / f"{mood}_{name}.png").convert("RGBA").resize(base.size, Image.Resampling.LANCZOS)
            layer = edit.copy()
            layer.putalpha(changed_mask(base, edit, EDITS[name]))
            out[f"{mood}_{name}"] = layer
    return out


def missing_sources(raw_dir: Path) -> list[Path]:
    parts = raw_dir / "parts"
    needed = [raw_dir / f"{mood}.png" for mood in MOODS]  # all eight: they decide the common crop
    needed += [parts / "idle.png", *(parts / f"{name}.png" for name in EDITS)]
    needed += [parts / f"{mood}_{name}.png" for mood, names in MOOD_EDITS.items() for name in names]
    return [path for path in needed if not path.is_file()]


def main(raw_dir: Path, out_dir: Path, height: int = 512) -> int:
    missing = missing_sources(raw_dir)
    if missing:  # never a half-updated set: new sprites with stale parts would not match
        for path in missing:
            print(f"[missing] {path}")
        print("nothing written")
        return 1
    images = load_raw(raw_dir)
    union = union_box(images)
    out_dir.mkdir(parents=True, exist_ok=True)
    every = {**layers(raw_dir / "parts", images.get("talk")), **mood_layers(raw_dir / "parts", images)}
    for name, layer in every.items():
        part = crop_scale(layer, union, height)
        part.save(out_dir / f"{name}.png", optimize=True)
        print(f"[ok] {name} {part.size}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 512))
