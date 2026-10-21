"""Special days for her first greeting of the day: fixed festivals, a few lunar ones, 主人's birthday.

There is no lunar calendar in the standard library, so the lunar festivals are a table (2026–2030);
past its end they are simply not greeted.
"""
from __future__ import annotations

import datetime

FIXED = {
    (1, 1): "元旦", (2, 14): "情人节", (5, 1): "劳动节", (6, 1): "儿童节",
    (10, 1): "国庆节", (12, 24): "平安夜", (12, 25): "圣诞节",
}
_SPRING = {2026: (2, 17), 2027: (2, 6), 2028: (1, 26), 2029: (2, 13), 2030: (2, 3)}
_DRAGON_BOAT = {2026: (6, 19), 2027: (6, 9), 2028: (5, 28), 2029: (6, 16), 2030: (6, 5)}
_MID_AUTUMN = {2026: (9, 25), 2027: (9, 15), 2028: (10, 3), 2029: (9, 22), 2030: (9, 12)}


def _lunar() -> dict[datetime.date, str]:
    days: dict[datetime.date, str] = {}
    for year, (month, day) in _SPRING.items():
        spring = datetime.date(year, month, day)
        days[spring] = "春节"
        days[spring - datetime.timedelta(days=1)] = "除夕"
    for table, name in ((_DRAGON_BOAT, "端午节"), (_MID_AUTUMN, "中秋节")):
        for year, (month, day) in table.items():
            days[datetime.date(year, month, day)] = name
    return days


LUNAR = _lunar()


def festival(day: datetime.date) -> str | None:
    return LUNAR.get(day) or FIXED.get((day.month, day.day))


def clean_birthday(value: object) -> str:
    """"MM-DD" for a real day of the year (29 February included), else "" (no birthday set)."""
    if not isinstance(value, str) or len(value) != 5 or value[2] != "-":
        return ""
    try:
        month, day = int(value[:2]), int(value[3:])
        datetime.date(2028, month, day)  # a leap year, so 02-29 is a valid birthday
    except ValueError:
        return ""
    return f"{month:02d}-{day:02d}"


def is_birthday(day: datetime.date, birthday: str) -> bool:
    if not birthday:
        return False
    month, date_ = int(birthday[:2]), int(birthday[3:])
    if (month, date_) == (2, 29) and not _leap(day.year):
        return (day.month, day.day) == (2, 28)  # celebrated the day before in other years
    return (day.month, day.day) == (month, date_)


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
