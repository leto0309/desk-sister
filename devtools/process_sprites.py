"""Turn generated art (assets/raw/<mood>.png) into app sprites (assets/sprites/<mood>.png).

- keeps real transparency; if a sheet has an opaque white background, removes the white
  that is connected to the image border (the dark outline keeps the white dress intact)
- crops every mood to the same union box, so switching expression never makes her jump
- scales to a fixed height

usage: python devtools/process_sprites.py <raw_dir> <out_dir> [height]
"""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from PIL import Image

MOODS = ("idle", "talk", "happy", "think", "panic", "angry", "sad", "sleep")


def remove_border_white(image: Image.Image, tolerance: int = 18) -> Image.Image:
    image = image.convert("RGBA")
    width, height = image.size
    pixels = image.load()

    def is_bg(x: int, y: int) -> bool:
        r, g, b, a = pixels[x, y]
        return a > 0 and min(r, g, b) >= 255 - tolerance

    queue = deque((x, y) for x in range(width) for y in (0, height - 1))
    queue.extend((x, y) for y in range(height) for x in (0, width - 1))
    seen = set()
    while queue:
        x, y = queue.popleft()
        if (x, y) in seen or not (0 <= x < width and 0 <= y < height):
            continue
        seen.add((x, y))
        if not is_bg(x, y):
            continue
        pixels[x, y] = (255, 255, 255, 0)
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return image


def has_transparency(image: Image.Image) -> bool:
    return image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < 16


def main(raw_dir: Path, out_dir: Path, height: int = 512) -> int:
    images: dict[str, Image.Image] = {}
    for mood in MOODS:
        path = raw_dir / f"{mood}.png"
        if not path.is_file():
            print(f"[missing] {path}")
            continue
        image = Image.open(path).convert("RGBA")
        if not has_transparency(image):
            print(f"[white bg -> alpha] {mood}")
            image = remove_border_white(image)
        images[mood] = image
    if not images:
        print("no sprites found")
        return 1
    sizes = {img.size for img in images.values()}
    if len(sizes) != 1:
        print(f"[warn] differing canvas sizes {sizes}; union box uses each image's own coordinates")
    boxes = [img.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox() for img in images.values()]
    boxes = [b for b in boxes if b]
    margin = 8
    union = (
        max(min(b[0] for b in boxes) - margin, 0), max(min(b[1] for b in boxes) - margin, 0),
        max(b[2] for b in boxes) + margin, max(b[3] for b in boxes) + margin,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    for mood, image in images.items():
        cropped = image.crop(union)
        scale = height / cropped.height
        cropped = cropped.resize((round(cropped.width * scale), height), Image.Resampling.LANCZOS)
        cropped.save(out_dir / f"{mood}.png", optimize=True)
        print(f"[ok] {mood} {cropped.size}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 512))
