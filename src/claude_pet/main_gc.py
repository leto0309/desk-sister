"""Python's cyclic garbage collector, run on the GUI thread only.

Left alone, the collector runs in whichever thread happens to cross its threshold. In a worker thread (a model call,
the Codex clean-up, her voice) it destroys Qt objects there, and Qt cannot stop a timer from another thread: the GUI
thread's event loop later sends a timer event to an object that is gone, which is an access violation (seen in the
tests on 2026-11-10, in QCoreApplication::notifyInternal2). So the automatic collector is switched off, and a timer
on the GUI thread collects when the collector's own thresholds are passed, and fully every few minutes.
"""
from __future__ import annotations

import gc
import time

from PySide6.QtCore import QObject, QTimer

CHECK_MS = 2000  # how often the thresholds are looked at
FULL_EVERY_SEC = 300.0  # a full collection at least this often, whatever the counters say


class MainThreadCollector(QObject):
    """Made on the GUI thread, once, before any worker thread starts."""

    def __init__(self, parent: QObject | None = None, clock=time.monotonic, interval_ms: int = CHECK_MS) -> None:
        super().__init__(parent)
        self._clock = clock
        self._was_enabled = gc.isenabled()
        gc.disable()
        self._full_at = clock() + FULL_EVERY_SEC
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.check)
        self._timer.start()

    def check(self) -> int | None:
        """Collect if it is time: the generation collected (the younger ones go with it), or None."""
        generation = self._due()
        if generation is None:
            return None
        gc.collect(generation)
        if generation == 2:
            self._full_at = self._clock() + FULL_EVERY_SEC
        return generation

    def _due(self) -> int | None:
        if self._clock() >= self._full_at:
            return 2
        counts, thresholds = gc.get_count(), gc.get_threshold()
        if not thresholds[0] or counts[0] <= thresholds[0]:
            return None  # nothing new enough to look at (only the first threshold at 0 means "never")
        # As CPython does: the oldest generation whose count is past its threshold. An older threshold of 0 is not
        # "never" but "whenever its count is above 0" (Codex's review, 2026-11-10).
        return max(g for g in range(3) if counts[g] > thresholds[g])

    def stop(self) -> None:
        """Back to how the collector was before (the tests use this; the app keeps it until it exits)."""
        self._timer.stop()
        if self._was_enabled:
            gc.enable()
