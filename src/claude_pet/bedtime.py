"""How often she may remind 主人 to go to bed.

Late at night she used to bring it up in almost every comment. Now the model's comments and her own
self-talk share one "last reminded" time: by default once a night, or at most every two hours, or never.
Whenever a reply at night mentions sleep or rest, that counts as the reminder.
"""
from __future__ import annotations

import datetime
import re

from .i18n import N_

MODES = ("off", "nightly", "every_2h")
MODE_LABELS = {"off": N_("关闭"), "nightly": N_("一晚一次"), "every_2h": N_("每 2 小时一次")}  # shown through tr()
NIGHT_STARTS = (20, 21, 22, 23, 0, 1, 2)  # hours the night may start at
NIGHT_END = 5  # the night is over at 5:00
GAP_SEC = 2 * 3600
_MENTION = re.compile(r"睡|休息|熬夜|晚安|\b(?:sleep(?:s|ing|y)?|slept|asleep|beds?|bedtime|rest|resting|"
                      r"stay(?:s|ing)? up|good ?night)\b", re.IGNORECASE)

# What the model is told at night.
MAY = "已经很晚了，这次可以顺带关心一句主人休息（只说一句，不要说教）。"
MAY_NOT = "这次不要主动提睡觉、休息或熬夜。"
MAY_EN = "It is very late: this time you may add one caring word about getting some rest (one sentence, no lecture)."
MAY_NOT_EN = "This time do not bring up sleep, rest or staying up late."


def is_night(hour: int, start: int) -> bool:
    if start >= NIGHT_END:
        return hour >= start or hour < NIGHT_END
    return start <= hour < NIGHT_END


def night_of(timestamp: float) -> str:
    """Which night a moment belongs to: before 5:00 on the wall clock it is still the evening before's
    night (wall-clock hours, so a daylight-saving change never splits a night in two)."""
    moment = datetime.datetime.fromtimestamp(timestamp)
    return str(moment.date() - datetime.timedelta(days=1 if moment.hour < NIGHT_END else 0))


def may_remind(mode: str, now: float, last: float) -> bool:
    """At night: whether one more reminder is allowed now (`last` is 0 when there never was one)."""
    if mode == "nightly":
        try:
            return last <= 0 or night_of(last) != night_of(now)
        except (OSError, OverflowError, ValueError):  # a time the platform cannot convert: as if none
            return True
    if mode == "every_2h":
        return last <= 0 or now - last >= GAP_SEC or now < last  # a clock set back never blocks forever
    return False


def mentions(text: str) -> bool:
    return bool(_MENTION.search(text))
