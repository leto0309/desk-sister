"""Her whole body moving, made from the one drawing per mood: a landing squash, a mood reaction, a swing when carried,
and now and then an idle action (a stretch, a look around, a sway, a doze at night) with the eye parts she already has.

Everything here is a transform of the finished frame (head movements included) about her feet, or about the point
she is held by. Nothing is drawn anew, so at rest she looks exactly as drawn.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform

DURATIONS = {"land": 0.5, "hop": 0.55, "stomp": 0.6, "shiver": 0.7, "slump": 2.6,
             "stretch": 2.6, "look": 3.4, "sway": 3.0, "doze": 3.6}
IDLE_ACTIONS = ("stretch", "look", "sway")  # while she stands idle; "doze" joins them at night
NIGHT_ACTIONS = ("doze",)
IDLE_EVERY = (60.0, 120.0)  # seconds between two idle actions
REACTIONS = {"happy": "hop", "angry": "stomp", "panic": "shiver", "sad": "slump"}  # mood -> movement
SHIVER_HZ = 5.0  # fast enough to read as a tremble, slow enough for frames 60 ms apart to show it
SWING_MAX = 9.0  # degrees either way while carried
SWING_LIMIT = 12.0  # with the overshoot; less when the window leaves little room at her sides
SWING_PULL = 0.012  # degrees per pixel/second of sideways drag
SWING_SPRING = 60.0
SWING_DAMPING = 5.0


def _ease(t: float, rise: float, hold: float, fall: float) -> float:
    """0 -> 1 over `rise`, stays for `hold`, back to 0 over `fall` (smooth at both ends)."""
    if t < rise:
        u = t / rise
    elif t < rise + hold:
        return 1.0
    else:
        u = max(0.0, 1 - (t - rise - hold) / fall)
    return u * u * (3 - 2 * u)


def _ramp(t: float, start: float, end: float) -> float:
    u = min(max((t - start) / (end - start), 0.0), 1.0)
    return u * u * (3 - 2 * u)


def eyes(kind: str, t: float) -> str | None:
    """The eye part an idle action shows at `t` (None: her own eyes)."""
    if kind == "stretch":
        e = _ramp(t, 0.0, 0.9) * (1 - _ramp(t, 1.7, 2.3))
        return "eyes_closed" if e > 0.6 else "eyes_half" if e > 0.25 else None
    if kind == "look":  # a blink on the way across
        return "eyes_closed" if 1.55 < t < 1.65 else "eyes_half" if 1.5 < t < 1.7 else None
    if kind == "doze" and 0 <= t <= 2.35:
        e = _ramp(t, 0.2, 1.8)
        return "eyes_closed" if e > 0.55 else "eyes_half" if e > 0.15 else None
    return None


def pose(kind: str, t: float, width: int, height: int, sign: int = 1) -> tuple[float, float, float, float, float] | None:
    """(dx, dy, degrees, x scale, y scale) about her feet, `t` seconds into a movement; None once it is over."""
    if kind not in DURATIONS or t < 0 or t >= DURATIONS[kind]:
        return None
    if kind == "land":  # squashed by the landing, then a springy stretch that settles
        d = math.exp(-7 * t) * math.cos(2 * math.pi * t / 0.28)
        return 0.0, 0.0, 0.0, 1 + 0.07 * d, 1 - 0.14 * d
    if kind == "hop":  # crouch, a little jump, a soft landing
        if t < 0.1:
            s = math.sin(math.pi * t / 0.1)
            return 0.0, 0.0, 0.0, 1 + 0.03 * s, 1 - 0.06 * s
        if t < 0.45:
            u = math.sin(math.pi * (t - 0.1) / 0.35)
            return 0.0, -0.07 * height * u, 0.0, 1 - 0.015 * u, 1 + 0.03 * u
        s = math.sin(math.pi * (t - 0.45) / 0.1)
        return 0.0, 0.0, 0.0, 1 + 0.02 * s, 1 - 0.04 * s
    if kind == "stomp":  # two stamps, leaning into each
        n, u = divmod(t / 0.3, 1.0)
        lift = math.sin(math.pi * u) ** 2
        lean = (1 if n % 2 == 0 else -1) * sign
        return 0.0, -0.025 * height * lift, 1.5 * lean * math.sin(math.pi * u), 1.0, 1.0
    if kind == "shiver":  # a quick side-to-side tremble that dies away
        fade = 1 - t / DURATIONS["shiver"]
        return 0.015 * width * math.sin(2 * math.pi * SHIVER_HZ * t) * fade, 0.0, 0.0, 1.0, 1.0
    if kind == "stretch":  # up on her toes, a little wobble at the top, then down with a small squash
        e = _ramp(t, 0.0, 0.9) * (1 - _ramp(t, 1.7, 2.3))
        wobble = sign * 0.7 * math.sin(2 * math.pi * (t - 0.9) / 0.8) if 0.9 < t < 1.7 else 0.0
        settle = -0.02 * math.sin(math.pi * (t - 2.3) / 0.3) if t > 2.3 else 0.0
        return 0.0, -0.012 * height * e, wobble * e, 1 - 0.02 * e - settle / 2, 1 + 0.055 * e + settle
    if kind == "look":  # lean to one side and hold, across to the other, back
        lean = sign * (-_ramp(t, 0.0, 0.4) + 2 * _ramp(t, 1.3, 1.9) - _ramp(t, 2.8, 3.4))
        return 0.018 * width * lean, -0.004 * height * abs(lean), 2.0 * lean, 1.0, 1.0
    if kind == "sway":  # humming: a slow rock from side to side
        env = _ramp(t, 0.0, 0.4) * (1 - _ramp(t, 2.6, 3.0))
        s = sign * math.sin(2 * math.pi * t / 1.5)
        return 0.0, -0.006 * height * abs(s) * env, 2.0 * s * env, 1.0, 1.0
    if kind == "doze":  # eyes grow heavy, she sinks and droops to one side, then jolts awake
        e = _ramp(t, 0.2, 1.8) * (1 - _ramp(t, 2.3, 2.45))
        jolt = math.sin(math.pi * (t - 2.3) / 0.35) if 2.3 < t < 2.65 else 0.0
        return 0.0, -0.025 * height * jolt, sign * 1.8 * e, 1 + 0.01 * e, 1 - 0.03 * e + 0.02 * jolt
    e = _ease(t, 0.5, 1.6, 0.5)  # slump: shoulders down, a slow sway
    return 0.0, 0.0, sign * 1.8 * e * math.sin(2 * math.pi * t / 1.3), 1 + 0.01 * e, 1 - 0.035 * e


def about_feet(feet: QPointF, dx: float, dy: float, angle: float, sx: float, sy: float) -> QTransform:
    t = QTransform()
    t.translate(feet.x() + dx, feet.y() + dy)
    t.rotate(angle)
    t.scale(sx, sy)
    t.translate(-feet.x(), -feet.y())
    return t


def about_hand(hand: QPointF, angle: float) -> QTransform:
    """Hanging from where she is held: turned about that point."""
    t = QTransform()
    t.translate(hand.x(), hand.y())
    t.rotate(angle)
    t.translate(-hand.x(), -hand.y())
    return t


def swing_limit(window_width: int, sprite_width: int, sprite_height: int) -> float:
    """How far she may swing without her hair leaving the window (measured: comfortably inside at every size)."""
    margin = max(0.0, (window_width - sprite_width) / 2)
    room = math.degrees(math.asin(min(1.0, 1.3 * margin / max(1, sprite_height))))
    return min(SWING_LIMIT, room)


def swing_step(angle: float, speed: float, drag_vx: float, dt: float, limit: float = SWING_LIMIT) -> tuple[float, float]:
    """One step of her swing: pulled back against the way she is carried, springing back when still."""
    reach = min(SWING_MAX, limit)
    target = max(-reach, min(reach, drag_vx * SWING_PULL))  # Qt turns clockwise on screen: her body trails behind
    speed += (SWING_SPRING * (target - angle) - SWING_DAMPING * speed) * dt
    angle = angle + speed * dt
    if abs(angle) > limit:
        angle, speed = math.copysign(limit, angle), 0.0
    return angle, speed


def settled(angle: float, speed: float) -> bool:
    return abs(angle) < 0.2 and abs(speed) < 1.0
