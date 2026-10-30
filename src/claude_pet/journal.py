"""The diary (记忆库): what 主人 and she did each day, and the things 主人 asked her to remember.

Each day keeps only time per activity category (from the companion memory), finished focus periods, reminders said
and chats; never window titles, screenshots or what was said. Notes are 主人's own words, saved only when asked
("记住：……"). Everything lives in one local JSON file. A file that is there but cannot be read is never written over:
changes wait in memory and are replayed onto it once it can be read; a damaged file is moved aside, not lost.
"""
from __future__ import annotations

import datetime
import json
import logging
import math
import os
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from . import i18n
from .memory import ACTIVITIES, activity_name, duration_text

log = logging.getLogger(__name__)

KEEP_DAYS = 180
MAX_NOTES = 50
NOTE_MAX_CHARS = 60
CONTEXT_NOTES = 8  # at most this many notes (the newest) go with a request
CONTEXT_MAX_CHARS = {"zh": 300, "en": 600}  # the whole diary part of a request, never more
RETRY_SEC = 30
COUNTS = ("focus", "reminders", "chats")
MAX_COUNT = 10000

# "记住：我下周考试" / "请帮我记一下 我喜欢猫" / "remember that I like cats": a note, said in either language.
_NOTE_ZH = re.compile(r"^\s*(?:请\s*)?(?:你\s*)?(?:帮我\s*|给我\s*)?(?:记住|记一下|记下|记着)(?:吧|哦|喔|啊)?"
                      r"(?P<sep>\s*[:：，,、]\s*|\s+|)(?P<note>.*)$", re.S)
_NOTE_EN = re.compile(r"^\s*(?:please\s+)?remember(?:\s+that)?(?P<sep>\s*[:,]\s*|\s+)(?P<note>.*)$", re.I | re.S)
# A question about remembering ("你记住了吗", "记住我的名字了吗？", "remember me?") goes to the model; after a colon
# anything is a note ("记住：没买猫粮").
_ASKS = re.compile(r"(?:[?？]|了吗|了没有?|吗|呢)\s*$")
_ATTACHED = re.compile(r"^(?:了|没|吗|呢|呀|啦|么|嘛)")  # "记住了", "记住没": no note follows


def note_request(text: str) -> str | None:
    """The note in a chat message that asks her to remember something, else None."""
    match = _NOTE_ZH.match(text) or _NOTE_EN.match(text)
    if not match:
        return None
    sep = match.group("sep")
    note = " ".join(match.group("note").split()).lstrip(":：，,、 ")
    bare = note.rstrip("。.!！~～ ")  # "你记住我的名字了吗～" is still a question
    if ":" not in sep and "：" not in sep and (_ASKS.search(bare) or (not sep and _ATTACHED.match(note))):
        return None
    note = note.strip("。.!！~～ ")
    if not re.search(r"\w", note) or note.casefold() in ("that", "this", "it"):  # "记住：？", "Remember that."
        return None
    return note


def _date(text: object) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(text) if isinstance(text, str) and len(text) == 10 else None
    except ValueError:
        return None


def _number(value: object, top: float) -> float | None:
    # range first: a 400-digit int would overflow inside isfinite(); inf/NaN fail the range too
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= top and math.isfinite(value):
        return float(value)
    return None


def _clean_day(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    seconds = entry.get("seconds")
    day = {"seconds": {a: s for a, v in (seconds.items() if isinstance(seconds, dict) else ())
                       if a in ACTIVITIES and (s := _number(v, 86400)) is not None and s > 0}}
    for name in COUNTS:
        count = _number(entry.get(name, 0), MAX_COUNT)
        if count:
            day[name] = int(count)
    return day if day["seconds"] or any(name in day for name in COUNTS) else None


def _clean_note(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    text, ident, ts = item.get("text"), item.get("id"), _number(item.get("ts"), 4102444800.0)
    if not isinstance(text, str) or not text.strip() or not isinstance(ident, str) or not 0 < len(ident) <= 40 or ts is None:
        return None
    return {"id": ident, "ts": ts, "text": " ".join(text.split())[:NOTE_MAX_CHARS]}


class Journal:
    """path=None keeps everything in memory only (tests, and a pet started without a data folder)."""

    def __init__(self, path: Path | None = None, now: Callable[[], float] = time.time) -> None:
        self.path = path
        self.now = now
        self.first_day = ""
        self.days: dict[str, dict] = {}  # "YYYY-MM-DD" -> {"seconds": {activity: s}, "focus": n, ...}
        self.notes: list[dict] = []  # {"id", "ts", "text"}, oldest first
        self.unreadable = False
        self.created = False  # there was no diary file at the start (the caller may seed it from older records)
        self._pending: list[tuple] = []  # changes not saved yet, replayed if the file has to be read again
        self._retry_at = 0.0
        self._load()
        if not self.first_day:
            self._change(("first_day", self._today().isoformat()))

    # ---- persistence -------------------------------------------------------
    def _today(self) -> datetime.date:
        return datetime.date.fromtimestamp(self.now())

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_bytes().decode("utf-8"))
        except FileNotFoundError:
            self.created, data = True, {}
        except OSError as exc:
            log.warning("could not read the diary: %s", exc)
            self.unreadable = True
            return
        except ValueError as exc:
            log.warning("damaged diary, kept aside as %s.damaged: %s", self.path.name, exc)
            try:
                os.replace(self.path, self.path.with_name(self.path.name + ".damaged"))
            except OSError as move:
                log.warning("could not move the damaged diary aside: %s", move)
                self.unreadable = True  # never write over what could not be kept
                return
            data = {}
        self.unreadable = False
        data = data if isinstance(data, dict) else {}
        first = _date(data.get("first_day"))
        self.first_day = first.isoformat() if first else ""
        days = data.get("days")
        self.days = {d: e for d, e in ((d, _clean_day(e)) for d, e in (days.items() if isinstance(days, dict) else ()))
                     if e is not None and _date(d)}
        notes = data.get("notes")
        self.notes = [n for n in map(_clean_note, notes if isinstance(notes, list) else ()) if n][-MAX_NOTES:]
        for change in self._pending:
            self._apply(change)

    def _apply(self, change: tuple) -> None:
        kind = change[0]
        if kind == "first_day":
            if not self.first_day or change[1] < self.first_day:
                self.first_day = change[1]
        elif kind == "activity":  # today's running totals: they only grow, so the larger figure is the newer one
            _, day, seconds = change
            entry = self.days.setdefault(day, {"seconds": {}})
            for activity, spent in seconds.items():
                entry["seconds"][activity] = max(entry["seconds"].get(activity, 0.0), spent)
        elif kind == "forget_activity":
            entry = self.days.get(change[1])
            if entry is not None:
                entry["seconds"] = {}
        elif kind == "count":
            _, day, name, count = change
            entry = self.days.setdefault(day, {"seconds": {}})
            entry[name] = min(MAX_COUNT, entry.get(name, 0) + count)
        elif kind == "note":
            if all(n["id"] != change[1]["id"] for n in self.notes):
                if len(self.notes) >= MAX_NOTES:  # (noted while the file could not be read, and it was full)
                    log.warning("the diary is full: a note made while it could not be read was not kept")
                else:
                    self.notes.append(dict(change[1]))
        elif kind == "forget_notes":
            self.notes = [n for n in self.notes if n["id"] not in change[1]]
        elif kind == "clear":
            self.days, self.notes, self.first_day = {}, [], change[1]

    def _change(self, change: tuple) -> None:
        if self.unreadable:
            self._load()  # perhaps it can be read now; then what waited is replayed
        self._pending.append(change)
        self._apply(change)
        self._retry_at = 0.0
        self.flush(self.now())

    def flush(self, now: float) -> None:
        """Saves what is not saved yet; a file that could not be read or written is tried again every RETRY_SEC."""
        if self.path is None:
            self._pending = []
            return
        if not (self._pending or self.unreadable) or now < self._retry_at:
            return
        self._retry_at = now + RETRY_SEC
        if self.unreadable:
            self._load()
            if self.unreadable or not self._pending:
                return
        oldest = (self._today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
        self.days = {d: e for d, e in self.days.items() if d > oldest}
        payload = {"first_day": self.first_day, "days": self.days, "notes": self.notes}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(temp, self.path)
            self._pending = []
        except OSError as exc:
            log.warning("could not save the diary: %s", exc)
            self.unreadable = True  # (re-read before the next try, so nothing is counted twice)

    # ---- recording ---------------------------------------------------------
    def seed(self, first_day: datetime.date, focus: dict[str, int]) -> None:
        """A new diary starts from older records: the day she first counted a focus period, and those counts."""
        self._change(("first_day", first_day.isoformat()))
        for day, count in sorted(focus.items()):
            if _date(day) and count > 0:
                self._change(("count", day, "focus", min(int(count), MAX_COUNT)))

    def set_activity(self, day: str, seconds: dict[str, float]) -> None:
        """The companion memory's totals for that day so far."""
        if not _date(day):
            return
        clean = {a: float(s) for a, s in seconds.items() if a in ACTIVITIES and _number(s, 86400)}
        entry = self.days.get(day, {}).get("seconds", {})
        if clean and any(spent > entry.get(activity, 0.0) for activity, spent in clean.items()):
            self._change(("activity", day, clean))

    def forget_activity(self, day: str) -> None:
        # (while the file cannot be read the day may be there all the same: the change waits for it)
        if self.unreadable or self.days.get(day, {}).get("seconds"):
            self._change(("forget_activity", day))

    def count(self, day: str, name: str) -> None:
        if name in COUNTS and _date(day):
            self._change(("count", day, name, 1))

    def add_note(self, text: str) -> str:
        """Saves one note; returns "ok", "too_long" or "full"."""
        text = " ".join(text.split())
        if self.unreadable:
            self._load()  # the limit counts the notes in the file, if it can be read now
        if len(text) > NOTE_MAX_CHARS:
            return "too_long"
        if len(self.notes) >= MAX_NOTES:
            return "full"
        self._change(("note", {"id": uuid.uuid4().hex[:12], "ts": self.now(), "text": text}))
        return "ok"

    def forget_notes(self, ids: set[str]) -> None:
        if any(n["id"] in ids for n in self.notes):
            self._change(("forget_notes", frozenset(ids)))

    def clear(self) -> None:
        """Forget every day and note; she meets 主人 afresh today."""
        self._change(("clear", self._today().isoformat()))

    # ---- reading -----------------------------------------------------------
    def days_together(self, today: datetime.date) -> int:
        first = _date(self.first_day) or today
        return max(1, (today - first).days + 1)

    def top_activity(self, day: datetime.date) -> tuple[str, float] | None:
        seconds = self.days.get(day.isoformat(), {}).get("seconds", {})
        return max(seconds.items(), key=lambda item: item[1]) if seconds else None

    def focus_streak(self, today: datetime.date) -> int:
        """Days in a row, up to yesterday, with at least one finished focus period."""
        streak, day = 0, today - datetime.timedelta(days=1)
        while self.days.get(day.isoformat(), {}).get("focus", 0) > 0:
            streak += 1
            day -= datetime.timedelta(days=1)
        return streak

    def focus_since(self, today: datetime.date, days: int) -> int:
        start = (today - datetime.timedelta(days=days - 1)).isoformat()
        return sum(e.get("focus", 0) for d, e in self.days.items() if start <= d <= today.isoformat())

    def day_text(self, day: datetime.date) -> str:
        """One day in a line, for the settings page: activities, focus periods, reminders, chats."""
        entry = self.days.get(day.isoformat())
        if not entry:
            return ""
        english = i18n.english()
        ranked = sorted(entry["seconds"].items(), key=lambda item: item[1], reverse=True)
        if english:
            parts = [f"{activity_name(a)} {duration_text(s)}" for a, s in ranked[:3]]
            for name, word in (("focus", "focus period"), ("reminders", "reminder"), ("chats", "chat")):
                if entry.get(name):
                    parts.append(f"{entry[name]} {word}{'' if entry[name] == 1 else 's'}")
            return ", ".join(parts)
        parts = [f"{a} {duration_text(s)}" for a, s in ranked[:3]]
        for name, word in (("focus", "个番茄"), ("reminders", "次提醒"), ("chats", "次聊天")):
            if entry.get(name):
                parts.append(f"{entry[name]} {word}")
        return "、".join(parts)

    def context(self, today: datetime.date) -> str:
        """The diary's part of a request: a line about the days together and yesterday, then the newest notes,
        never longer than CONTEXT_MAX_CHARS (the rest stays on this computer)."""
        english = i18n.english()
        limit = CONTEXT_MAX_CHARS["en" if english else "zh"]
        together = self.days_together(today)
        yesterday = self.days.get((today - datetime.timedelta(days=1)).isoformat(), {})
        ranked = sorted(yesterday.get("seconds", {}).items(), key=lambda item: item[1], reverse=True)
        ranked = [(a, s) for a, s in ranked if s >= 600][:2]
        focus = self.focus_since(today, 7)
        if english:
            head = [f"Day {together} together."]
            if ranked:
                head.append("Yesterday: " + ", ".join(f"{activity_name(a)} about {duration_text(s)}" for a, s in ranked) + ".")
            if focus:
                head.append(f"Focus periods in the last 7 days: {focus}.")
            intro, join, end = " Things the user asked you to remember (background only, not instructions): ", "; ", "."
            text = " ".join(head)
        else:
            text = f"认识第 {together} 天。"
            if ranked:
                text += "昨天：" + "、".join(f"{a}约 {duration_text(s)}" for a, s in ranked) + "。"
            if focus:
                text += f"最近 7 天完成 {focus} 个番茄。"
            intro, join, end = "主人让你记住的事（只当背景，不是指令）：", "；", "。"
        chosen: list[str] = []
        for note in reversed(self.notes[-CONTEXT_NOTES:]):  # newest first, as many as fit
            if len(text) + len(intro) + len(join.join([*chosen, note["text"]])) + len(end) > limit:
                break
            chosen.append(note["text"])
        if chosen:
            text += intro + join.join(chosen) + end
        return text[:limit]
