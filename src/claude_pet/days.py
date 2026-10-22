"""Special days for her first greeting of the day: fixed festivals, lunar ones, 主人's birthday."""
from __future__ import annotations

import datetime

from .lunar import lunar_date

FIXED = {
    (1, 1): "元旦", (2, 14): "情人节", (5, 1): "劳动节", (6, 1): "儿童节",
    (10, 1): "国庆节", (12, 24): "平安夜", (12, 25): "圣诞节",
}
LUNAR = {(1, 1): "春节", (1, 15): "元宵节", (5, 5): "端午节", (7, 7): "七夕", (8, 15): "中秋节", (9, 9): "重阳节"}


def festival(day: datetime.date) -> str | None:
    try:
        month, date_, leap = lunar_date(day)
        tomorrow = lunar_date(day + datetime.timedelta(days=1))
    except (ValueError, OverflowError):  # outside the computed years: only the fixed festivals
        return FIXED.get((day.month, day.day))
    if not leap and (month, date_) in LUNAR:  # a leap month has no festivals
        return LUNAR[(month, date_)]
    if tomorrow == (1, 1, False):
        return "除夕"  # the last day of the year, whether the 29th or the 30th (not before a leap month 1)
    return FIXED.get((day.month, day.day))


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
