"""The focus timer (pomodoro) and the reminders 主人 sets: local only, on the wall clock.

The wall clock (time.time) keeps counting while the PC sleeps, so a timer that ran out meanwhile is due at once on
waking. Nothing here talks or draws; the controller asks what is due each second and says it.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

FOCUS_RANGE = (5, 120)  # minutes
BREAK_RANGE = (1, 60)
MAX_REMINDERS = 20
MAX_TEXT = 100
MISSED_AFTER_SEC = 120.0  # said this late, a reminder says when it was for
FORGET_AFTER_SEC = 12 * 3600.0
RETRY_READ_SEC = 30.0  # a reminders file another program held: read again this often  # one missed by longer than this (the pet was not running) is dropped


class Pomodoro:
    """Focus, then a short break, then focus again, until stopped. Pausing freezes the time left."""

    def __init__(self) -> None:
        self.phase: str | None = None  # "focus" or "break" while running
        self.ends_at = 0.0
        self.paused_left: float | None = None
        self.done = 0  # focus periods finished since the start
        self.focus_sec = 0.0  # the length of the focus period now running (or last finished)

    @property
    def running(self) -> bool:
        return self.phase is not None

    @property
    def paused(self) -> bool:
        return self.paused_left is not None

    def start(self, now: float, focus_sec: float) -> None:
        self.phase, self.ends_at, self.paused_left, self.done = "focus", now + focus_sec, None, 0
        self.focus_sec = focus_sec

    def stop(self) -> int:
        """Ends it; returns how many focus periods were finished."""
        done, self.phase, self.paused_left, self.done = self.done, None, None, 0
        return done

    def pause(self, now: float) -> None:
        if self.running and not self.paused:
            self.paused_left = max(0.0, self.ends_at - now)

    def resume(self, now: float) -> None:
        if self.paused:
            self.ends_at, self.paused_left = now + self.paused_left, None

    def left(self, now: float) -> float:
        if not self.running:
            return 0.0
        return self.paused_left if self.paused else max(0.0, self.ends_at - now)

    def due(self, now: float, focus_sec: float, break_sec: float) -> str | None:
        """"focus_done" or "break_done" when a period ran out (the next one starts now), else None."""
        if not self.running or self.paused or now < self.ends_at:
            return None
        if self.phase == "focus":
            self.done += 1
            self.phase, self.ends_at = "break", now + break_sec
            return "focus_done"
        self.phase, self.ends_at, self.focus_sec = "focus", now + focus_sec, focus_sec
        return "break_done"


@dataclass
class Reminder:
    due: float
    text: str
    id: str


class Reminders:
    """Reminders kept in a small JSON file, so they outlive a restart."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.items: list[Reminder] = []
        self.unreadable = False  # the file is there but could not be read: never overwrite it then
        self._retry_at = 0.0
        self._load()

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            self.unreadable = False
            return
        except OSError as exc:  # held by another program, say: try again before any change
            log.warning("could not read reminders: %s", exc)
            self.unreadable = True
            return
        self.unreadable = False
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as exc:  # damaged for good (bad JSON, not UTF-8): kept aside, and a fresh list starts
            log.warning("damaged reminders file kept as .bad: %s", exc)
            try:
                os.replace(self.path, self.path.with_name(self.path.name + ".bad"))
            except OSError:
                self.unreadable = True
            return
        items = []
        for item in data if isinstance(data, list) else []:
            try:
                due, text, ident = float(item["due"]), str(item["text"]).strip(), str(item["id"])
                datetime.datetime.fromtimestamp(due)  # a time this PC can show (not NaN, negative or huge)
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                continue
            if text:
                items.append(Reminder(due, text[:MAX_TEXT], ident))
        self.items = sorted(items, key=lambda r: r.due)[:MAX_REMINDERS]

    def _readable(self) -> None:
        """Before a change: a file that could not be read is read now, or the change is refused (OSError)."""
        if self.unreadable:
            self._load()
            if self.unreadable:
                raise OSError("the reminders file cannot be read right now")

    def _write(self, items: list[Reminder]) -> None:
        """Saves `items` whole (written aside, then swapped in). Raises OSError; the caller keeps the old list then."""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps([asdict(r) for r in items], ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, self.path)

    def add(self, due: float, text: str) -> Reminder | None:
        """None when the list is full or the text is empty; OSError when it could not be saved (then not added)."""
        text = " ".join(text.split())[:MAX_TEXT]
        self._readable()
        if not text or len(self.items) >= MAX_REMINDERS:
            return None
        reminder = Reminder(due, text, uuid.uuid4().hex[:12])
        items = sorted(self.items + [reminder], key=lambda r: r.due)
        self._write(items)
        self.items = items
        return reminder

    def cancel(self, ident: str) -> Reminder | None:
        """The cancelled one, or None if there is no such; OSError when it could not be saved (then still there)."""
        self._readable()
        for reminder in self.items:
            if reminder.id == ident:
                items = [r for r in self.items if r is not reminder]
                self._write(items)
                self.items = items
                return reminder
        return None

    def due_now(self, now: float) -> Reminder | None:
        """The oldest one whose time has come. It stays saved until finish(), so a restart never loses it.
        A file that could not be read is tried again now and then, so its reminders come back by themselves."""
        if self.unreadable and now >= self._retry_at:
            self._retry_at = now + RETRY_READ_SEC
            self._load()
        first = self.next()
        return first if first is not None and first.due <= now else None

    def finish(self, ident: str) -> None:
        """Said (or dropped as too old): gone. If the file cannot be updated it may be said again after a restart."""
        items = [r for r in self.items if r.id != ident]
        self.items = items
        try:
            self._readable()
            items = [r for r in self.items if r.id != ident]  # (re-read: keep what the file had)
            self.items = items
            self._write(items)
        except OSError as exc:
            log.warning("could not save reminders: %s", exc)

    def next(self) -> Reminder | None:
        return self.items[0] if self.items else None


class FocusLog:
    """How many focus periods were finished each day, and for how long: a small JSON file, the last 60 days.

    A file that is there but cannot be read (another program holds it) is never written over: what is finished
    meanwhile waits in memory and is merged in as soon as the file can be read again."""

    KEEP_DAYS = 60

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.days: dict[str, dict[str, float]] = {}
        self.unreadable = False
        self._unsaved: list[tuple[str, float]] = []  # (day, seconds) finished and not saved yet
        self._retry_at = 0.0
        self._load()

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_bytes().decode("utf-8"))
        except FileNotFoundError:
            data = {}
        except OSError as exc:
            log.warning("could not read the focus log: %s", exc)
            self.unreadable = True
            return
        except ValueError as exc:
            log.warning("damaged focus log, starting afresh: %s", exc)
            data = {}
        self.unreadable = False
        days = {}
        for day, entry in (data.items() if isinstance(data, dict) else ()):
            try:
                datetime.date.fromisoformat(day)
                count, seconds = int(entry["count"]), float(entry["seconds"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if count > 0 and 0 <= seconds < 86400 * 2:
                days[day] = {"count": count, "seconds": seconds}
        self.days = days
        for day, seconds in self._unsaved:
            self._count(day, seconds)

    def _count(self, day: str, seconds: float) -> None:
        entry = self.days.setdefault(day, {"count": 0, "seconds": 0.0})
        entry["count"] += 1
        entry["seconds"] += max(0.0, seconds)

    def add(self, when: float, seconds: float) -> None:
        """One more focus period, finished at `when` (wall clock), counted for that day and saved if it can be."""
        day = datetime.date.fromtimestamp(when).isoformat()
        if self.unreadable:
            self._load()  # perhaps it can be read now; then what waited is merged in
        self._unsaved.append((day, seconds))
        self._count(day, seconds)
        self._retry_at = 0.0
        self.flush(when)

    def flush(self, now: float) -> None:
        """Saves what is not saved yet. Called each second too: a file that could not be read or written is
        tried again every RETRY_READ_SEC, so nothing waits for the next period (or is lost at the next start)."""
        if self.path is None:
            self._unsaved = []
            return
        if not (self._unsaved or self.unreadable) or now < self._retry_at:
            return
        self._retry_at = now + RETRY_READ_SEC
        if self.unreadable:
            self._load()  # also with nothing to save: the days it holds come back for the menu and summary
            if self.unreadable or not self._unsaved:
                return
        newest = max(self.days) if self.days else datetime.date.fromtimestamp(now).isoformat()
        oldest = (datetime.date.fromisoformat(newest) - datetime.timedelta(days=self.KEEP_DAYS)).isoformat()
        self.days = {d: e for d, e in self.days.items() if d > oldest}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(json.dumps(self.days, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(temp, self.path)
            self._unsaved = []
        except OSError as exc:
            log.warning("could not save the focus log: %s", exc)
            self.unreadable = True  # (re-read before the next try, so nothing is counted twice)

    def on(self, day: datetime.date) -> tuple[int, float]:
        """(periods, seconds) finished that day."""
        entry = self.days.get(day.isoformat())
        return (int(entry["count"]), float(entry["seconds"])) if entry else (0, 0.0)


def due_in(now: float, minutes: int) -> float:
    return now + max(1, int(minutes)) * 60.0


def due_at(now: float, hour: int, minute: int) -> float:
    """The next time the wall clock shows hour:minute: today, or tomorrow if that has passed."""
    today = datetime.datetime.fromtimestamp(now)
    moment = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment.timestamp() <= now:
        moment = (moment + datetime.timedelta(days=1)).replace(hour=hour, minute=minute)
    return moment.timestamp()


def clock_text(timestamp: float) -> str:
    return datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M")


def left_text(seconds: float) -> str:
    """25:00, 4:59, 1:05:00: counting down, so a part second shows as the whole second still to go."""
    whole = max(0, int(-(-seconds // 1)))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
