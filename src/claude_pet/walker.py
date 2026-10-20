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
ON_FLOOR = 2  # pixels of slack for "standing on the floor"
GRAVITY = 3000.0  # pixels per second squared: a drop of 80 px takes about 0.23 s
TOP_SPEED = 1800.0  # pixels per second: a fall from the top of the screen still reads as a fall


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
                 rng: random.Random | None = None, clock: Callable[[], float] = time.monotonic,
                 edge: Callable[[], None] | None = None, landed: Callable[[], None] | None = None) -> None:
        super().__init__(window)
        self.window = window
        self.can_walk = can_walk
        self.arrived = arrived
        self.rng = rng or random.Random()
        self.clock = clock
        self.edge = edge  # a stroll ended at the edge of the screen
        self.landed = landed  # a drop above the floor has landed
        self.enabled = False
        self.target: float | None = None
        self.falling = False
        self._y = 0.0
        self._vy = 0.0
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
            self._cancel_fall()
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

    def fall_to_floor(self) -> None:
        """After a drop she falls onto the floor from any height (from below it: straight up onto it).
        `arrived` is called once she stands; `falling` tells whether she is still on her way down."""
        self.falling = False  # a new drop replaces a fall she was caught in
        self._frame.stop()
        if self.walking:
            self.stop()  # grabbed and dropped before the next frame: the stroll ends here
        if self.floor_y() - self.window.y() <= 0:
            self.land_now()
            self.rest()
            return
        self.window.move(QPoint(self._clamped_x(self.window.x()), self.window.y()))
        self.falling = True
        self._y = float(self.window.y())
        self._vy = 0.0
        self._last = self.clock()
        self._frame.start()

    def _cancel_fall(self) -> None:
        """Walking switched off on the way down: she stays where she is (and that place is remembered)."""
        if not self.falling:
            return
        self.falling = False
        self._vy = 0.0
        self._frame.stop()
        self.arrived(self.window.x(), self.window.y())

    def land_now(self) -> None:
        """Stand on the floor at once (at start-up), wherever she was."""
        self.window.move(QPoint(self._clamped_x(self.window.x()), self.floor_y()))

    def _bounds(self) -> tuple[int, int]:
        area = self.work_area()
        return area.x(), area.x() + area.width() - self.window.width()

    def _clamped_x(self, x: int) -> int:
        left, right = self._bounds()
        return min(max(x, left), max(left, right))

    # ---- walking --------------------------------------------------------
    def start_stroll(self) -> None:
        if not self.enabled or self.walking or self.falling:
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

    def _fall(self) -> None:
        if getattr(self.window, "grabbed", False):
            # Held on the way down: she hangs there. A click lets go and she falls on; a drag ends in a
            # new drop, which starts over from wherever she is put.
            self._last = self.clock()
            self._vy = 0.0
            return
        if abs(self.window.y() - round(self._y)) > 1:
            self._y = float(self.window.y())  # moved from outside (say, resized): fall on from where she is
        now = self.clock()
        dt, self._last = min(now - self._last, 0.05), now
        self._vy = min(self._vy + GRAVITY * dt, TOP_SPEED)
        self._y += self._vy * dt
        floor = self.floor_y()
        if self._y >= floor:
            self._y = floor
        self.window.move(QPoint(self.window.x(), round(self._y)))
        if self._y >= floor:
            self.falling = False
            self._frame.stop()
            self.arrived(self.window.x(), self.window.y())
            if self.landed:
                self.landed()
            self.rest()

    def step(self) -> None:
        if self.falling:
            self._fall()
            return
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
            at_edge = min(abs(self.target - left), abs(self.target - right)) < 0.5
            self.stop()
            if at_edge and self.edge:
                self.edge()

    def stop(self) -> None:
        """Stand still where she is (and remember that place); the next stroll comes after a rest."""
        if not self.falling:  # a fall always lands
            self._frame.stop()
        if not self.walking:
            return
        self.target = None
        self.window.set_walking(0)
        self.arrived(self.window.x(), self.window.y())
        self.rest()
