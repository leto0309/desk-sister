"""Strolling along the bottom of the screen.

When she stands on the bottom edge of the screen's work area (just above the taskbar), she now and then
walks a little way to the left or right and stops again. She never leaves that screen, never sets off
while she is talking, asleep, being dragged or keeping quiet for a full-screen program, and stops at
once when one of those starts. A frame timer runs only while she is actually walking.
"""
from __future__ import annotations

import random
import time
from typing import Callable

from PySide6.QtCore import QObject, QPoint, QRect, QTimer
from PySide6.QtGui import QGuiApplication

SPEED = 60.0  # pixels per second
FRAME_MS = 33  # about 30 frames per second, only while walking
REST_SEC = (25.0, 70.0)  # pause between two strolls
DISTANCE = (80.0, 350.0)  # length of one stroll
SNAP = 80  # dropped this close above the floor, she lands on it
ON_FLOOR = 2  # pixels of slack for "standing on the floor"


def plan_stroll(x: float, left: float, right: float, rng: random.Random) -> float | None:
    """Where to walk to from `x`, staying within [left, right] (the window's left edge); None when
    there is no room for a real stroll either way."""
    distance = rng.uniform(*DISTANCE)
    direction = rng.choice((-1, 1))
    room = {-1: x - left, 1: right - x}
    if room[direction] < DISTANCE[0]:
        direction = -direction
    if room[direction] < DISTANCE[0]:
        return None  # not even the shortest stroll fits either way
    return x + direction * min(distance, room[direction])


class Walker(QObject):
    def __init__(self, window, can_walk: Callable[[], bool], arrived: Callable[[int, int], None],
                 rng: random.Random | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(window)
        self.window = window
        self.can_walk = can_walk
        self.arrived = arrived
        self.rng = rng or random.Random()
        self.clock = clock
        self.enabled = False
        self.target: float | None = None
        self._x = 0.0  # exact position between frames, so slow speeds do not round away
        self._last = 0.0
        self._rest = QTimer(self, singleShot=True, timeout=self.start_stroll)
        self._frame = QTimer(self, interval=FRAME_MS, timeout=self.step)

    # ---- switching -----------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        if self.enabled:
            if not self.walking:
                self.rest()
        else:
            self.stop()
            self._rest.stop()

    def rest(self) -> None:
        if self.enabled:
            self._rest.start(int(self.rng.uniform(*REST_SEC) * 1000))

    @property
    def walking(self) -> bool:
        return self.target is not None

    # ---- where the floor is --------------------------------------------
    def work_area(self) -> QRect:
        centre = self.window.geometry().center()
        screen = QGuiApplication.screenAt(centre) or self.window.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def floor_y(self) -> int:
        """The window's y when her feet stand on the bottom of the work area."""
        area = self.work_area()
        return area.y() + area.height() - self.window.height()

    def on_floor(self) -> bool:
        return abs(self.window.y() - self.floor_y()) <= ON_FLOOR

    def snap_to_floor(self) -> bool:
        """After a drop: close above (or a little below) the floor means standing on it."""
        floor = self.floor_y()
        if self.window.y() == floor:
            return True
        if abs(floor - self.window.y()) <= SNAP:
            self.window.move(QPoint(self._clamped_x(self.window.x()), floor))
            return True
        return False

    def _bounds(self) -> tuple[int, int]:
        area = self.work_area()
        return area.x(), area.x() + area.width() - self.window.width()

    def _clamped_x(self, x: int) -> int:
        left, right = self._bounds()
        return min(max(x, left), max(left, right))

    # ---- walking --------------------------------------------------------
    def start_stroll(self) -> None:
        if not self.enabled or self.walking:
            return
        if not self.can_walk() or not self.on_floor():
            self.rest()  # try again later
            return
        left, right = self._bounds()
        target = plan_stroll(self.window.x(), left, right, self.rng)
        if target is None:
            self.rest()
            return
        self.target = target
        self._x = float(self.window.x())
        self._last = self.clock()
        self.window.set_walking(1 if target > self._x else -1)
        self._frame.start()

    def step(self) -> None:
        if not self.walking:
            self._frame.stop()
            return
        if not self.enabled or not self.can_walk():
            self.stop()  # she started talking, was grabbed, fell asleep...
            return
        now = self.clock()
        dt, self._last = min(now - self._last, 0.25), now  # a stalled UI never makes her jump far
        if abs(self.window.x() - round(self._x)) > 1:
            self._x = float(self.window.x())  # moved from outside (say, resized): go on from where she is
        left, right = self._bounds()
        self.target = min(max(self.target, left), max(left, right))  # the screen edge, even for a wider window
        if abs(self.target - self._x) < 0.5:
            self.stop()
            return
        direction = 1 if self.target > self._x else -1
        self._x += direction * SPEED * dt
        done = (self._x - self.target) * direction >= 0
        if done:
            self._x = self.target
        self.window.move(QPoint(round(self._x), self.window.y()))
        if done:
            self.stop()

    def stop(self) -> None:
        """Stand still where she is (and remember that place); the next stroll comes after a rest."""
        self._frame.stop()
        if not self.walking:
            return
        self.target = None
        self.window.set_walking(0)
        self.arrived(self.window.x(), self.window.y())
        self.rest()
