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
from process_sprites import crop_scale, load_raw, union_box  # noqa: E402

EYES = (385, 225, 630, 330)  # areas in the 1024 x 1024 raw canvas
MOUTH = (455, 315, 550, 380)
EDITS = {"eyes_half": EYES, "eyes_closed": EYES, "mouth_half": MOUTH, "mouth_open": MOUTH, "mouth_o": MOUTH}
PARTS = (*EDITS, "mouth_closed")


def changed_mask(base: Image.Image, edit: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    r, g, b = ImageChops.difference(edit.convert("RGB"), base.convert("RGB")).split()
    strongest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    area = Image.new("L", base.size, 0)
    area.paste(255, box)
    mask = ImageChops.multiply(strongest.point(lambda v: 255 if v > 30 else 0), area)
    mask = mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
    return ImageChops.multiply(ImageChops.multiply(mask, area), base.getchannel("A"))


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
    return out


def main(raw_dir: Path, out_dir: Path, height: int = 512) -> int:
    images = load_raw(raw_dir)
    if not images:
        print("no raw sprites found")
        return 1
    union = union_box(images)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, layer in layers(raw_dir / "parts", images.get("talk")).items():
        part = crop_scale(layer, union, height)
        part.save(out_dir / f"{name}.png", optimize=True)
        print(f"[ok] {name} {part.size}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 512))
