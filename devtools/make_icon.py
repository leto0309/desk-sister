"""Make assets/icon.ico (her head, 16-256 px) from the idle sprite.

    python devtools/make_icon.py [--preview out.png]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "sprites" / "idle.png"
TARGET = ROOT / "assets" / "icon.ico"
HEAD = (112, 24, 312, 224)  # square around the face and the flower, in sprite pixels
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def head(source: Path = SOURCE) -> Image.Image:
    sprite = Image.open(source).convert("RGBA")
    return sprite.crop(HEAD).resize((256, 256), Image.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path, help="also write a PNG preview of the 256 px image")
    args = parser.parse_args()
    image = head()
    image.save(TARGET, sizes=SIZES)
    if args.preview:
        image.save(args.preview)
    print(f"wrote {TARGET.relative_to(ROOT)} ({TARGET.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
