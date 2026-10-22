"""The computed lunar calendar against published dates (Hong Kong Observatory tables, as in the lunardate package).

During development every day of 2000–2099 was compared with lunardate: no differences.
"""
import datetime

import pytest

from claude_pet import lunar

SPRING = ["2024-02-10", "2025-01-29", "2026-02-17", "2027-02-06", "2028-01-26", "2029-02-13", "2030-02-03",
          "2031-01-23", "2032-02-11", "2033-01-31", "2034-02-19", "2035-02-08", "2036-01-28", "2037-02-15",
          "2038-02-04", "2039-01-24", "2040-02-12", "2047-01-26", "2054-02-08", "2061-01-21", "2068-02-03",
          "2075-02-15", "2082-01-29", "2089-02-10", "2096-01-25"]
# (year, leap month, its first day)
LEAP = [(2025, 6, "2025-07-25"), (2028, 5, "2028-06-23"), (2031, 3, "2031-04-22"), (2033, 11, "2033-12-22"),
        (2036, 6, "2036-07-23"), (2042, 2, "2042-03-22"), (2044, 7, "2044-08-23"), (2052, 8, "2052-09-23"),
        (2058, 4, "2058-05-22"), (2071, 8, "2071-09-24"), (2090, 8, "2090-09-24"), (2099, 2, "2099-03-22")]


@pytest.mark.parametrize("day", SPRING)
def test_spring_festival(day):
    day = datetime.date.fromisoformat(day)
    assert lunar.lunar_date(day) == (1, 1, False)
    assert lunar.lunar_date(day - datetime.timedelta(days=1))[0] == 12


@pytest.mark.parametrize(("year", "month", "day"), LEAP)
def test_leap_months(year, month, day):
    day = datetime.date.fromisoformat(day)
    assert lunar.lunar_date(day) == (month, 1, True)
    assert lunar.lunar_date(day - datetime.timedelta(days=1))[:2] in ((month, 29), (month, 30))
    assert lunar.lunar_date(day - datetime.timedelta(days=1))[2] is False


def test_the_last_month_has_29_or_30_days():
    assert lunar.lunar_date(datetime.date(2024, 2, 9)) == (12, 30, False)
    assert lunar.lunar_date(datetime.date(2025, 1, 28)) == (12, 29, False)


def test_every_day_of_a_year_follows_on():
    day = datetime.date(2033, 1, 1)
    previous = lunar.lunar_date(day - datetime.timedelta(days=1))
    while day.year < 2035:
        today = lunar.lunar_date(day)
        assert today[1] == previous[1] + 1 or (today[1] == 1 and previous[1] in (29, 30))
        previous, day = today, day + datetime.timedelta(days=1)
