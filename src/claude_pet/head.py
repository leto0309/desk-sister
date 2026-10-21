"""Small head movements: a nod as she starts a line, a tilt now and then, a duck when she is patted.

The head is cut just under the chin with a soft band (the mask is made once per size), and the long
hair at her sides stays with the body, so a small turn of the head shows no seam. Only while the head moves is a frame put
together off screen; standing still she is drawn as before.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter, QPixmap, QTransform

NECK = 0.355  # where the head ends, as a share of the sprite's height (just under the chin)
BAND = 0.04  # the soft cut between head and body
PIVOT_X = 0.49  # the neck, as a share of the width
SIDE_START, SIDE_FADE = 0.42, 0.14  # long side hair: still beyond this share of the width from the neck
LOW_START, LOW_FADE = 0.22, 0.10  # ... but only below this height; the crown turns with her head
TILT_EVERY = (15.0, 40.0)  # seconds between two idle tilts
DURATIONS = {"nod": 0.45, "tilt": 2.4, "duck": 1.0}


def _clamp(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


def head_mask(width: int, height: int) -> QImage:
    """How much of each pixel belongs to the head (alpha 255) rather than the body (0)."""
    neck, band = NECK * height, BAND * height
    pivot = PIVOT_X * width
    side = [_clamp((SIDE_START * width - abs(x - pivot)) / (SIDE_FADE * width)) for x in range(width)]
    stride = (width + 3) // 4 * 4
    data = bytearray(stride * height)
    for y in range(height):
        vertical = _clamp((neck + band / 2 - y) / band)
        if vertical == 0:
            continue
        low = _clamp((y - LOW_START * height) / (LOW_FADE * height))
        row = y * stride
        if low == 0:
            data[row:row + width] = bytes([round(255 * vertical)]) * width
        else:
            data[row:row + width] = bytes(round(255 * vertical * (1 - low * (1 - s))) for s in side)
    return QImage(bytes(data), width, height, stride, QImage.Format.Format_Alpha8).copy()


def _ease(t: float, rise: float, hold: float, fall: float) -> float:
    """0 -> 1 over `rise`, stays for `hold`, back to 0 over `fall` (smooth at both ends)."""
    if t < rise:
        u = t / rise
    elif t < rise + hold:
        return 1.0
    else:
        u = max(0.0, 1 - (t - rise - hold) / fall)
    return u * u * (3 - 2 * u)


def pose(kind: str, t: float, height: int, sign: int = 1) -> tuple[float, float, float] | None:
    """(degrees, pixels down, vertical scale) of the head `t` seconds into a movement; None once over."""
    if t < 0 or t >= DURATIONS[kind]:
        return None
    if kind == "nod":
        e = math.sin(math.pi * t / DURATIONS["nod"])
        return 0.5 * e, 0.01 * height * e, 1.0
    if kind == "tilt":
        return sign * 1.5 * _ease(t, 0.4, 1.6, 0.4), 0.0, 1.0
    e = _ease(t, 0.15, 0.6, 0.25)  # duck
    return 0.0, 0.012 * height * e, 1 - 0.025 * e


def transform(width: int, height: int, angle: float, dy: float, scale_y: float) -> QTransform:
    pivot = QPointF(PIVOT_X * width, NECK * height)
    t = QTransform()
    t.translate(pivot.x(), pivot.y() + dy)
    t.rotate(angle)
    t.scale(1.0, scale_y)
    t.translate(-pivot.x(), -pivot.y())
    return t


def _layer(layers: list[QPixmap], size, moved: QTransform | None) -> QImage:
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if moved is not None:
        painter.setTransform(moved)
    for layer in layers:
        painter.drawPixmap(0, 0, layer)
    painter.end()
    return image


def _cut(image: QImage, mask: QImage, keep_head: bool) -> QImage:
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn if keep_head
                               else QPainter.CompositionMode.CompositionMode_DestinationOut)
    painter.drawImage(0, 0, mask)
    painter.end()
    return image


def compose(layers: list[QPixmap], mask: QImage, moved: QTransform) -> QImage:
    """The sprite (with its face parts) as it is below the neck, moved above it. The head is moved
    first and cut with the fixed mask after, so the two soft edges always add up to one picture."""
    size = layers[0].size()
    frame = _cut(_layer(layers, size, None), mask, keep_head=False)
    top = _cut(_layer(layers, size, moved), mask, keep_head=True)
    painter = QPainter(frame)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.drawImage(0, 0, top)
    painter.end()
    return frame
