"""Special days for her first hello: festivals and 主人's birthday."""
import datetime

import pytest

from claude_pet import days
from claude_pet.config import Config


@pytest.mark.parametrize(("day", "name"), [
    ((2027, 1, 1), "元旦"), ((2026, 10, 1), "国庆节"), ((2026, 12, 25), "圣诞节"),
    ((2027, 2, 5), "除夕"), ((2027, 2, 6), "春节"), ((2026, 6, 19), "端午节"), ((2026, 9, 25), "中秋节"),
    ((2026, 10, 21), None),
    ((2031, 1, 22), "除夕"), ((2031, 1, 23), "春节"), ((2031, 2, 6), "元宵节"),  # computed, not a table
    ((2026, 8, 19), "七夕"), ((2026, 10, 18), "重阳节"),
    ((2034, 2, 18), "除夕"), ((2034, 2, 19), "春节"),  # after the leap 11th month of 2033
    ((2050, 1, 23), "春节"), ((2099, 1, 21), "春节"),
    ((2028, 5, 28), "端午节"), ((2028, 6, 27), None),  # the 5th of leap month 5 is no festival
])
def test_festivals(day, name):
    assert days.festival(datetime.date(*day)) == name


def test_no_new_year_s_eve_before_a_leap_first_month(monkeypatch):
    lunar = {datetime.date(2262, 3, 5): (1, 29, False), datetime.date(2262, 3, 6): (1, 1, True)}
    monkeypatch.setattr(days, "lunar_date", lambda day: lunar[day])
    assert days.festival(datetime.date(2262, 3, 5)) is None


@pytest.mark.parametrize("day", [datetime.date.min, datetime.date(1900, 1, 1), datetime.date(2201, 1, 1),
                                 datetime.date.max])
def test_outside_the_computed_years_only_fixed_festivals(day):
    assert days.festival(day) == days.FIXED.get((day.month, day.day))
    assert days.festival(datetime.date(day.year, 12, 25)) == "圣诞节"


@pytest.mark.parametrize(("value", "clean"), [
    ("05-03", "05-03"), ("02-29", "02-29"), ("02-30", ""), ("13-01", ""), ("5-3", ""), ("ab-cd", ""),
    ("", ""), (None, ""), (503, ""), ("05/03", ""),
])
def test_clean_birthday(value, clean):
    assert days.clean_birthday(value) == clean


def test_birthday_on_its_day_and_29_february_on_the_28th_in_other_years():
    assert days.is_birthday(datetime.date(2026, 5, 3), "05-03")
    assert not days.is_birthday(datetime.date(2026, 5, 4), "05-03")
    assert not days.is_birthday(datetime.date(2026, 5, 3), "")
    assert days.is_birthday(datetime.date(2027, 2, 28), "02-29")
    assert days.is_birthday(datetime.date(2028, 2, 29), "02-29")
    assert not days.is_birthday(datetime.date(2028, 2, 28), "02-29")


def test_config_drops_a_bad_birthday_or_greeting_day():
    config = Config(birthday="02-31", greeted_on=20261021).normalized()
    assert config.birthday == "" and config.greeted_on == ""
    assert Config(birthday="12-01", greeted_on="2026-10-21").normalized().greeted_on == "2026-10-21"
