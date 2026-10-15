"""Decoding of the embedded sprites (no Qt here, so --self-test can use it without a display)."""
from __future__ import annotations

import base64
import hashlib
import io

from PIL import Image


def decode_embedded(data: str, sha256: str) -> Image.Image:
    """Verify and fully decode one base64 WebP sprite to RGBA; raises ValueError/OSError if damaged.

    A lossy WebP decoder can turn a damaged bitstream into garbled pixels without any error,
    so the bytes are checked against the checksum recorded at generation time first.
    Image.open() only reads the header; load() is what decodes the pixels.
    """
    raw = base64.b64decode(data, validate=True)
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("embedded sprite checksum mismatch")
    with Image.open(io.BytesIO(raw)) as image:
        if image.format != "WEBP":
            raise ValueError(f"expected WEBP, got {image.format}")
        image.load()
        return image.convert("RGBA")
