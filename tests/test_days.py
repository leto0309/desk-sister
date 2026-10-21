"""Special days for her first hello: festivals and 主人's birthday."""
import datetime

import pytest

from claude_pet import days
from claude_pet.config import Config


@pytest.mark.parametrize(("day", "name"), [
    ((2027, 1, 1), "元旦"), ((2026, 10, 1), "国庆节"), ((2026, 12, 25), "圣诞节"),
    ((2027, 2, 5), "除夕"), ((2027, 2, 6), "春节"), ((2026, 6, 19), "端午节"), ((2026, 9, 25), "中秋节"),
    ((2026, 10, 21), None), ((2031, 1, 23), None),  # an ordinary day; past the end of the lunar table
])
def test_festivals(day, name):
    assert days.festival(datetime.date(*day)) == name


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
