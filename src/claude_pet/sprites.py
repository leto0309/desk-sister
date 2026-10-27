"""Decoding of the embedded sprites (no Qt here, so --self-test can use it without a display)."""
from __future__ import annotations

import base64
import hashlib
import io

from PIL import Image


# The face parts the app expects (assets/sprites/parts/<name>.png and sprite_data.PART_*).
IDLE_PARTS = ("eyes_half", "eyes_closed", "mouth_half", "mouth_open", "mouth_o", "mouth_closed")  # idle and talk
MOOD_PARTS = {  # made from each expression's own sprite, named "<mood>_<part>"; happy and panic keep their eyes
    "happy": ("mouth_half", "mouth_open"),
    "think": ("mouth_half", "mouth_open", "eyes_half", "eyes_closed"),
    "panic": ("mouth_half", "mouth_open"),
    "angry": ("mouth_half", "mouth_open", "eyes_half", "eyes_closed"),
    "sad": ("mouth_half", "mouth_open", "eyes_half", "eyes_closed"),
}
TALK_EYES = ("talk_eyes_half", "talk_eyes_closed")  # idle's blink, also covering the talk sprite's own eyes
PARTS = IDLE_PARTS + TALK_EYES + tuple(f"{mood}_{part}" for mood, parts in MOOD_PARTS.items() for part in parts)


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


def sprite_module(girl: str):
    """The generated module holding a girl's embedded art, or None if she has none yet. Imported by name here,
    one by one, so a one-file build (which follows imports) carries every girl's art."""
    try:
        if girl == "claude":
            from . import sprite_data as module
        elif girl == "deepseek":
            from . import sprite_data_deepseek as module
        elif girl == "gpt":
            from . import sprite_data_gpt as module
        elif girl == "gemini":
            from . import sprite_data_gemini as module
        elif girl == "qwen":
            from . import sprite_data_qwen as module
        elif girl == "glm":
            from . import sprite_data_glm as module
        else:
            return None
    except ImportError:
        return None
    return module
