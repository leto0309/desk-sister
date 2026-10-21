"""The floating pet: a transparent, frameless, always-on-top window with a sprite and a speech bubble."""
from __future__ import annotations

import logging
import math
import random
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

from . import head
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


def embedded_sprite(mood: str, part: bool = False) -> QPixmap:
    """Sprite (or face part) from the generated module (a one-file exe has no assets folder). Decoded
    with Pillow, so it does not depend on Qt image-format plugins being bundled."""
    from . import sprite_data
    from .sprites import decode_embedded

    images = getattr(sprite_data, "PART_IMAGES", {}) if part else sprite_data.SPRITES
    checksums = getattr(sprite_data, "PART_CHECKSUMS", {}) if part else sprite_data.CHECKSUMS
    data = images.get(mood)
    if not data:
        return QPixmap()
    try:
        image = decode_embedded(data, checksums.get(mood, ""))
    except (OSError, ValueError, SyntaxError):
        log.exception("embedded %s %s is corrupt", "part" if part else "sprite", mood)
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


def load_parts(folder: Path, height: int) -> dict[str, QPixmap]:
    """Face overlay parts (assets/sprites/parts, else embedded). A missing part is simply not drawn."""
    parts: dict[str, QPixmap] = {}
    for name in PARTS:
        pixmap = QPixmap(str(folder / "parts" / f"{name}.png"))
        if pixmap.isNull():
            pixmap = embedded_sprite(name, part=True)
        if pixmap.isNull():
            log.warning("face part %s missing; she will not use it", name)
            continue
        parts[name] = pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    return parts


from .sprites import IDLE_PARTS, MOOD_PARTS, PARTS, TALK_EYES  # noqa: E402,F401  (shared with devtools)
FACE_MOODS = ("idle", "talk", *MOOD_PARTS)  # the sprites that have face parts
BLINK_EVERY = (3.0, 7.0)  # seconds between blinks, normally
BLINK_RATES = {"off": None, "few": (6.0, 12.0), "normal": BLINK_EVERY, "often": (1.5, 4.0)}
BLINK = ((0.07, "eyes_half"), (0.16, "eyes_closed"), (0.23, "eyes_half"))  # until this many seconds: this part
MOUTH_CYCLE = ("mouth_half", "mouth_open", "mouth_half", None)  # None: her mouth at rest
MOUTH_SET = ("mouth_half", "mouth_open")  # every shape the talking cycle uses
BLINK_SET = ("eyes_half", "eyes_closed")
MOUTH_FRAME = 0.15  # seconds each shape is held, however fast the words appear
PAUSE_HOLD = 4  # characters her mouth stays closed after a comma or full stop
PAUSES = set("，。！？、…～,.!?;；：:（）()「」『』—\n ")
STOPS = PAUSES - {" "}  # punctuation and line breaks pause her mouth; a space between words does not
HEAD_SHARE = 0.35  # the top part of the sprite that counts as her head
PAT_TURNS = 4  # direction changes ...
PAT_WINDOW = 1.5  # ... within this many seconds ...
PAT_STROKE = 12  # ... each after a stroke of at least this many pixels


class PetWindow(QWidget):
    poked = Signal()
    context_menu_requested = Signal(QPoint)
    moved = Signal(int, int)
    hotkey_pressed = Signal()
    resize_wheel = Signal(int)  # Ctrl + wheel over her: whole notches, + is bigger
    patted = Signal()  # the mouse rubbed back and forth over her head (no button held)

    def __init__(self, sprite_folder: Path, sprite_height: int = 220) -> None:
        # DoesNotAcceptFocus: clicking the pet must not steal the foreground from the window it comments on.
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Desk Sister")
        self.sprite_folder = sprite_folder
        self.sprite_height = sprite_height
        self.sprites = load_sprites(sprite_folder, sprite_height)
        self.parts = load_parts(sprite_folder, sprite_height)
        self._rng = random.Random()
        self._talk_started = 0.0
        self._paused_mouth = False
        self.eyes: str | None = None  # face parts drawn over the sprite right now
        self.mouth: str | None = None
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
        self._feet: tuple[float, QPoint] | None = None  # exact centre x after the last resize, and where it put us
        self.walking = 0  # -1 walking left, 1 walking right, 0 standing
        self._wheel = 0  # Ctrl + wheel: what a touchpad scrolled short of a whole notch
        self._lift_mood: str | None = None  # her mood before she was picked up
        self._carried_since = 0.0
        self.carried_for = 0.0  # how long the last drag lasted (seconds)
        self._rub: tuple[int, int, int] | None = None  # head pat: last x, direction, x where it last turned
        self._turns: list[float] = []  # when the rubbing changed direction
        self.setMouseTracking(True)  # hover moves too, for the head pat
        self._mirrored: dict[str, QPixmap] = {}
        self.blink_every: tuple[float, float] | None = BLINK_EVERY
        self.talk_mouth = True
        self.head_motion = False  # off until the settings switch it on
        self._head: tuple[str, float, int] | None = None  # (movement, started, direction) while one plays
        self._next_tilt = self.clock() + self._rng.uniform(*head.TILT_EVERY)
        self._head_mask: QImage | None = None
        self._blink_at = self.clock() + self._rng.uniform(*BLINK_EVERY)
        sprite_width = max(p.width() for p in self.sprites.values())
        self.bubble_area = 150
        self.setFixedSize(max(BUBBLE_WIDTH + 20, sprite_width), self.bubble_area + sprite_height + 8)

        self._typer = QTimer(self, interval=35, timeout=self._type_next)
        self._hide_bubble = QTimer(self, singleShot=True, timeout=self.clear_bubble)
        self._bob = QTimer(self, interval=60, timeout=self._animate)
        self._bob.start()

    def set_sprite_height(self, height: int) -> None:
        """Resize her live; her feet stay where they were (bottom centre of the window)."""
        if height == self.sprite_height:
            return
        old = self.geometry()
        # The centre is kept as a float between resizes, so back-and-forth resizing never drifts;
        # once she has been moved, her new place is the reference.
        centre = self._feet[0] if self._feet and self._feet[1] == old.topLeft() else old.x() + old.width() / 2
        self.sprite_height = height
        self.sprites = load_sprites(self.sprite_folder, height)
        self.parts = load_parts(self.sprite_folder, height)
        self._mirrored = {}
        self._head, self._head_mask = None, None  # a new size: a new mask, no movement
        sprite_width = max(p.width() for p in self.sprites.values())
        self.setFixedSize(max(BUBBLE_WIDTH + 20, sprite_width), self.bubble_area + height + 8)
        place = QPoint(round(centre - self.width() / 2), old.y() + old.height() - self.height())
        self.move(place)
        self._feet = (centre, place)
        self.update()

    # ---- state -------------------------------------------------------
    def set_walking(self, direction: int) -> None:
        self.walking = direction
        if direction:
            self._head = None  # walking hops already: a head movement under way ends here
        self.update()

    @property
    def grabbed(self) -> bool:
        return self._press_pos is not None

    def _sprite(self) -> QPixmap:
        return self._facing(self.mood, self.sprites[self.mood])

    def _facing(self, key: str, pixmap: QPixmap) -> QPixmap:
        if self.walking <= 0:
            return pixmap
        if key not in self._mirrored:  # walking right: she turns that way
            self._mirrored[key] = pixmap.transformed(QTransform().scale(-1, 1))
        return self._mirrored[key]

    def _layers(self) -> list[QPixmap]:
        """The sprite and the face parts over it, all the same size and drawn at the same place."""
        layers = [self._sprite()]
        if self.mood not in FACE_MOODS:
            return layers
        # The mouth first, then the eyes: a mouth part's soft edge may reach just under an eye.
        groups = [[self._part(self.mouth)], [self._part(self.eyes)]]
        if self.mood == "talk" and self.mouth and self.mouth != "mouth_closed":
            groups[0] = ["mouth_closed", self.mouth]  # cover the talk sprite's own open mouth first
        for names, whole in zip(groups, (self._set_ready(MOUTH_SET), self._set_ready(BLINK_SET))):
            if whole and all(name in self.parts for name in names):
                layers.extend(self._facing(name, self.parts[name]) for name in names)
        return layers

    def _set_ready(self, names: tuple[str, ...]) -> bool:
        """An animation is played whole or not at all: one missing frame drops the set for this face."""
        wanted = [self._part(name) for name in names]
        if self.mood == "talk" and names == MOUTH_SET:
            wanted.append("mouth_closed")
        return all(name in self.parts for name in wanted)

    def _part(self, name: str | None) -> str | None:
        """The part made for the current expression (talk shares idle's mouths and has its own blink)."""
        if name is None or self.mood == "idle":
            return name
        if self.mood == "talk":
            return f"talk_{name}" if name.startswith("eyes") else name
        return f"{self.mood}_{name}"

    def set_mood(self, mood: str) -> None:
        self.mood = mood if mood in self.sprites else "talk"
        self.update()

    def say(self, mood: str, text: str, hold_ms: int | None = None) -> None:
        self.last_said_at = self.clock()
        self.set_mood(mood)
        self.full_text = text
        self.shown_chars = 0
        self._talk_started = self.clock()
        self._paused_mouth = False
        self._typer.start()
        self._hide_bubble.start(hold_ms if hold_ms is not None else 6000 + 180 * len(text))
        self.start_head("nod")  # a little nod as she starts to talk

    def clear_bubble(self) -> None:
        self._typer.stop()
        self.mouth = None
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
        self.mouth = self._mouth_now()
        self.update()

    def set_blink(self, rate: str) -> None:
        """How often she blinks: off, few, normal or often (the settings window)."""
        self.blink_every = BLINK_RATES.get(rate, BLINK_EVERY)
        self.eyes = None  # an eye half way through a blink opens again at once
        if self.blink_every:
            self._blink_at = self.clock() + self._rng.uniform(*self.blink_every)
        self.update()

    def set_head_motion(self, enabled: bool) -> None:
        self.head_motion = bool(enabled)
        if not self.head_motion:
            self._head = None
        self.update()

    def start_head(self, kind: str) -> None:
        """Nod, tilt or duck, unless she is walking (hopping already), asleep or held."""
        if self._head_still():
            return
        self._head = (kind, self.clock(), self._rng.choice((-1, 1)))
        self.update()

    def _head_still(self) -> bool:
        """Whatever she is doing now rules a head movement out (it may have started before)."""
        return not self.head_motion or self.walking or self.mood == "sleep" or self._press_pos is not None

    def head_pose(self) -> tuple[float, float, float] | None:
        if self._head is not None and self._head_still():
            self._head = None  # stopped for good: it does not come back when she is free again
        if self._head is None:
            return None
        kind, started, sign = self._head
        return head.pose(kind, self.clock() - started, self.sprite_height, sign)

    def _mask(self) -> QImage:
        size = self.sprites[self.mood].size()
        if self._head_mask is None or self._head_mask.size() != size:  # one sprite may be wider than another
            self._head_mask = head.head_mask(size.width(), size.height())
        return self._head_mask

    def _move_head(self, now: float) -> None:
        if self._head is not None and self.head_pose() is None:
            self._head = None  # that movement is over, or she fell asleep, was picked up...
        if now < self._next_tilt:
            return
        self._next_tilt = now + self._rng.uniform(*head.TILT_EVERY)
        if self._head is None and not self.full_text and self.mood in ("idle", "talk", "happy", "think"):
            self.start_head("tilt")  # now and then, while she has nothing to say

    def set_talk_mouth(self, enabled: bool) -> None:
        self.talk_mouth = bool(enabled)
        if not self.talk_mouth:
            self.mouth = None
        self.update()

    def _mouth_now(self) -> str | None:
        """While the words appear her mouth moves; at a pause and once done it rests as drawn."""
        if (not self.talk_mouth or self.mood not in FACE_MOODS or not self._typer.isActive()
                or not self.shown_chars):
            return None
        rest = "mouth_closed" if self.mood == "talk" else None
        recent = self.full_text[max(0, self.shown_chars - PAUSE_HOLD):self.shown_chars]
        if any(ch in STOPS for ch in recent):
            self._paused_mouth = True  # a real pause after punctuation, not a flicker
            return rest
        if self._paused_mouth:
            self._paused_mouth = False
            self._talk_started = self.clock()  # start the rhythm afresh, so no shape is cut short
        frame = int((self.clock() - self._talk_started) / MOUTH_FRAME)
        return MOUTH_CYCLE[frame % len(MOUTH_CYCLE)] or rest

    def _blink(self, now: float) -> None:
        if self.mood not in FACE_MOODS or not self.blink_every:
            self.eyes = None
            return
        elapsed = now - self._blink_at
        self.eyes = None
        if elapsed < 0:
            return
        for until, part in BLINK:
            if elapsed < until:
                self.eyes = part
                return
        self._blink_at = now + self._rng.uniform(*self.blink_every)  # this blink is over: the next one

    def _animate(self) -> None:
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        self._blink(self.clock())
        self._move_head(self.clock())
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
        layers = self._layers()
        sprite = layers[0]
        x = (self.width() - sprite.width()) // 2
        if self.walking:
            # A little hop per step, leaning into each one: two steps a second.
            beat = self.clock() * 2 * math.pi * 2
            hop = round(5 * abs(math.sin(beat)))
            y = self.height() - sprite.height() - 4 - hop
            p.save()
            p.translate(self.width() / 2, self.height() - 4)
            p.rotate(3 * math.sin(beat / 2))
            p.translate(-self.width() / 2, -(self.height() - 4))
            for layer in layers:
                p.drawPixmap(x, y, layer)
            p.restore()
        else:
            bob = 0 if self.mood == "sleep" else round(2 * math.sin(self._phase))
            y = self.height() - sprite.height() - 4 + bob
            moved = self.head_pose()
            if moved is None:
                for layer in layers:
                    p.drawPixmap(x, y, layer)
            else:  # the head turns on its own: put the frame together off screen first
                frame = head.compose(layers, self._mask(), head.transform(sprite.width(), sprite.height(), *moved))
                p.drawImage(x, y, frame)
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

    def head_rect(self) -> QRect:
        sprite = self.sprites[self.mood]
        top = self.height() - sprite.height() - 4
        return QRect((self.width() - sprite.width()) // 2, top, sprite.width(), round(sprite.height() * HEAD_SHARE))

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None:
            self._track_rub(event.position().toPoint())
            return
        delta = event.globalPosition().toPoint() - self._press_pos
        if self._dragging or delta.manhattanLength() > DRAG_THRESHOLD:
            if not self._dragging:
                self._carried_since = self.clock()
            if not self._dragging and not self.full_text:
                self._lift_mood = self.mood
                self.set_mood("panic")  # picked up: legs dangling
            self._dragging = True
            self.move(self._origin + delta)

    def _track_rub(self, pos: QPoint) -> None:
        """A pat is the mouse rubbing back and forth over her head: enough turns, each a real stroke."""
        if not self.head_rect().contains(pos):
            self._rub, self._turns = None, []
            return
        now = self.clock()
        if self._rub is None:
            self._rub = (pos.x(), 0, pos.x())
            return
        last_x, direction, turned_at = self._rub
        step = (pos.x() > last_x) - (pos.x() < last_x)
        if step == 0:
            return
        if direction and step != direction:
            if abs(last_x - turned_at) >= PAT_STROKE:
                self._turns = [t for t in self._turns if now - t <= PAT_WINDOW] + [now]
            turned_at = last_x
        self._rub = (pos.x(), step, turned_at)
        if len(self._turns) >= PAT_TURNS:
            self._turns = []
            self.start_head("duck")
            self.patted.emit()

    def leaveEvent(self, _event) -> None:
        self._rub, self._turns = None, []

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._press_pos is None:
            return
        if self._lift_mood is not None:
            if self.mood == "panic" and not self.full_text:
                self.set_mood(self._lift_mood)  # put down again
            self._lift_mood = None
        if self._dragging:
            self.carried_for = self.clock() - self._carried_since  # read by whoever handles the drop
            self.moved.emit(self.x(), self.y())
        else:
            self.poked.emit()
        self._press_pos = None
        self._dragging = False

    def wheelEvent(self, event) -> None:
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._wheel = 0
            event.ignore()
            return
        self._wheel += event.angleDelta().y()
        notches = int(self._wheel / 120)  # toward zero, so the rest keeps its sign
        if notches:
            self._wheel -= notches * 120
            self.resize_wheel.emit(notches)
        event.accept()

    # ---- global hotkey (WM_HOTKEY arrives at this window) -------------
    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            import ctypes.wintypes

            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312:  # WM_HOTKEY
                self.hotkey_pressed.emit()
                return True, 0
        return super().nativeEvent(event_type, message)
