"""The floating pet: a transparent, frameless, always-on-top window with a sprite and a speech bubble."""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .persona import MOODS

log = logging.getLogger("claude_pet")

BUBBLE_WIDTH = 300
BUBBLE_PADDING = 14
TAIL = 12
DRAG_THRESHOLD = 6
STATUS_MARGIN = 8


def placeholder_sprite(mood: str, height: int) -> QPixmap:
    """Drawn when a sprite file is missing, so the pet still runs without art."""
    width = int(height * 0.7)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#3b2416"), 3))
    p.setBrush(QColor("#f6efe6"))
    p.drawRoundedRect(QRectF(width * 0.2, height * 0.5, width * 0.6, height * 0.45), 18, 18)
    p.setBrush(QColor("#e8743b"))
    p.drawEllipse(QRectF(width * 0.1, height * 0.05, width * 0.8, width * 0.8))
    p.setPen(QColor("#3b2416"))
    p.setFont(QFont("Microsoft YaHei UI", max(9, height // 18), QFont.Weight.Bold))
    p.drawText(QRectF(0, height * 0.05, width, width * 0.8), Qt.AlignmentFlag.AlignCenter, mood)
    p.end()
    return pixmap


def embedded_sprite(mood: str) -> QPixmap:
    """Sprite from the generated module (a one-file exe has no assets folder). Decoded with Pillow,
    so it does not depend on Qt image-format plugins being bundled."""
    from . import sprite_data
    from .sprites import decode_embedded

    data = sprite_data.SPRITES.get(mood)
    if not data:
        return QPixmap()
    try:
        image = decode_embedded(data, sprite_data.CHECKSUMS.get(mood, ""))
    except (OSError, ValueError, SyntaxError):
        log.exception("embedded sprite %s is corrupt", mood)
        return QPixmap()
    qimage = QImage(image.tobytes("raw", "RGBA"), image.width, image.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())  # copy: the QImage must not outlive the bytes it wraps


def fit_lines(text: str, metrics: QFontMetrics, width: int, max_lines: int = 2) -> list[str]:
    """Wrap to the real pixel width at character boundaries (preferring spaces), at most max_lines;
    the last line ends with an ellipsis when text is cut. The start of the text is always kept."""
    lines: list[str] = []
    rest = text.strip()
    while rest and len(lines) < max_lines:
        if metrics.horizontalAdvance(rest) <= width:
            lines.append(rest)
            rest = ""
            break
        cut = 1
        while cut < len(rest) and metrics.horizontalAdvance(rest[: cut + 1]) <= width:
            cut += 1
        space = rest.rfind(" ", 0, cut)
        if space > cut // 2:
            cut = space
        lines.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest and lines:
        last = lines[-1]
        while last and metrics.horizontalAdvance(last + "…") > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def load_sprites(folder: Path, height: int) -> dict[str, QPixmap]:
    """assets/sprites PNGs when present (source checkout), else the embedded copies, else placeholders."""
    sprites: dict[str, QPixmap] = {}
    for mood in MOODS:
        pixmap = QPixmap(str(folder / f"{mood}.png"))
        if pixmap.isNull():
            pixmap = embedded_sprite(mood)
        if pixmap.isNull():
            log.warning("sprite %s missing; drawing a placeholder", mood)
            sprites[mood] = placeholder_sprite(mood, height)
        else:
            sprites[mood] = pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    return sprites


class PetWindow(QWidget):
    poked = Signal()
    context_menu_requested = Signal(QPoint)
    moved = Signal(int, int)
    hotkey_pressed = Signal()

    def __init__(self, sprite_folder: Path, sprite_height: int = 220) -> None:
        # DoesNotAcceptFocus: clicking the pet must not steal the foreground from the window it comments on.
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Desk Sister")
        self.sprite_height = sprite_height
        self.sprites = load_sprites(sprite_folder, sprite_height)
        self.mood = "idle"
        self.full_text = ""
        self.shown_chars = 0
        self.bubble_font = QFont("Microsoft YaHei UI", 10)
        self.status = ""
        self.clock = time.monotonic
        self.last_said_at = float("-inf")
        self.status_font = QFont("Microsoft YaHei UI", 8)
        self._press_pos: QPoint | None = None
        self._dragging = False
        self._phase = 0.0
        sprite_width = max(p.width() for p in self.sprites.values())
        self.bubble_area = 150
        self.setFixedSize(max(BUBBLE_WIDTH + 20, sprite_width), self.bubble_area + sprite_height + 8)

        self._typer = QTimer(self, interval=35, timeout=self._type_next)
        self._hide_bubble = QTimer(self, singleShot=True, timeout=self.clear_bubble)
        self._bob = QTimer(self, interval=60, timeout=self._animate)
        self._bob.start()

    # ---- state -------------------------------------------------------
    def set_mood(self, mood: str) -> None:
        self.mood = mood if mood in self.sprites else "talk"
        self.update()

    def say(self, mood: str, text: str, hold_ms: int | None = None) -> None:
        self.last_said_at = self.clock()
        self.set_mood(mood)
        self.full_text = text
        self.shown_chars = 0
        self._typer.start()
        self._hide_bubble.start(hold_ms if hold_ms is not None else 6000 + 180 * len(text))

    def clear_bubble(self) -> None:
        self._typer.stop()
        self.full_text = ""
        self.shown_chars = 0
        if self.mood not in ("sleep",):
            self.mood = "idle"
        self.update()

    def set_status(self, status: str) -> None:
        self.status = status
        self.update()

    @property
    def visible_text(self) -> str:
        return self.full_text[: self.shown_chars]

    def _type_next(self) -> None:
        self.shown_chars += 1
        if self.shown_chars >= len(self.full_text):
            self.shown_chars = len(self.full_text)
            self._typer.stop()
        self.update()

    def _animate(self) -> None:
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        self.update()

    # ---- painting ----------------------------------------------------
    def _bubble_rect(self, text: str) -> QRect:
        metrics = QFontMetrics(self.bubble_font)
        inner = BUBBLE_WIDTH - 2 * BUBBLE_PADDING
        bound = metrics.boundingRect(QRect(0, 0, inner, 1000), Qt.TextFlag.TextWordWrap, text or " ")
        height = min(bound.height() + 2 * BUBBLE_PADDING, self.bubble_area - TAIL - 4)
        x = (self.width() - BUBBLE_WIDTH) // 2
        return QRect(x, self.bubble_area - TAIL - height, BUBBLE_WIDTH, height)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        sprite = self.sprites[self.mood]
        bob = 0 if self.mood == "sleep" else round(2 * math.sin(self._phase))
        x = (self.width() - sprite.width()) // 2
        y = self.height() - sprite.height() - 4 + bob
        p.drawPixmap(x, y, sprite)
        if self.full_text:
            self._paint_bubble(p, self.full_text, self.visible_text)
        if self.status:
            # Up to two lines, so an error reason stays readable in a screenshot.
            self._paint_status(p)
        p.end()

    def status_lines(self) -> list[str]:
        return fit_lines(self.status, QFontMetrics(self.status_font), self.width() - 2 * STATUS_MARGIN)

    def _paint_status(self, p: QPainter) -> None:
        # One layout feeds both the backing and the text, so neither can run past the window.
        p.setFont(self.status_font)
        metrics = QFontMetrics(self.status_font)
        lines = self.status_lines()
        line_height = metrics.height()
        widest = max(metrics.horizontalAdvance(line) for line in lines)
        right = self.width() - STATUS_MARGIN
        top = self.height() - 4 - line_height * len(lines)
        # A light backing keeps the text readable where it overlaps her feet.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 215))
        p.drawRoundedRect(QRectF(right - widest - 4, top - 2, widest + 8, line_height * len(lines) + 4), 6, 6)
        p.setPen(QColor(80, 80, 80))
        for i, line in enumerate(lines):
            p.drawText(QRect(STATUS_MARGIN, top + i * line_height, right - STATUS_MARGIN, line_height),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, line)

    def _paint_bubble(self, p: QPainter, full: str, shown: str) -> None:
        # Sized for the full line so the bubble does not grow while typing.
        rect = self._bubble_rect(full)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 14, 14)
        tail = QPainterPath()
        cx = self.width() // 2
        tail.moveTo(cx - 10, rect.bottom() - 1)
        tail.lineTo(cx, rect.bottom() + TAIL)
        tail.lineTo(cx + 10, rect.bottom() - 1)
        tail.closeSubpath()
        path = path.united(tail)
        p.setPen(QPen(QColor("#e8743b"), 2))
        p.setBrush(QColor(255, 251, 245, 245))
        p.drawPath(path)
        p.setPen(QColor("#3b2416"))
        p.setFont(self.bubble_font)
        inner = rect.adjusted(BUBBLE_PADDING, BUBBLE_PADDING, -BUBBLE_PADDING, -BUBBLE_PADDING)
        p.drawText(inner, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, shown)

    # ---- mouse -------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._origin = self.pos()
            self._dragging = False
        elif event.button() == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None:
            return
        delta = event.globalPosition().toPoint() - self._press_pos
        if self._dragging or delta.manhattanLength() > DRAG_THRESHOLD:
            self._dragging = True
            self.move(self._origin + delta)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._press_pos is None:
            return
        if self._dragging:
            self.moved.emit(self.x(), self.y())
        else:
            self.poked.emit()
        self._press_pos = None
        self._dragging = False

    # ---- global hotkey (WM_HOTKEY arrives at this window) -------------
    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            import ctypes.wintypes

            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312:  # WM_HOTKEY
                self.hotkey_pressed.emit()
                return True, 0
        return super().nativeEvent(event_type, message)
