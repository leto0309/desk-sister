"""The Chinese lunar calendar, computed rather than looked up, for the years FIRST_YEAR to LAST_YEAR.

A month starts on the day (Beijing time) of a new moon. The month holding the winter solstice is month 11.
A suì (solstice to solstice) with 13 months has one leap month: the first one with no principal solar term
(a multiple of 30° of the sun's longitude), as in GB/T 33661-2017. New moons and the sun follow Meeus,
*Astronomical Algorithms* (ch. 25 and 49): a few minutes off at most, which only matters on the rare day a new
moon falls right at midnight.
"""
from __future__ import annotations

import datetime
import math
from functools import lru_cache

FIRST_YEAR, LAST_YEAR = 1901, 2200  # checked against published tables for 2000–2099; ΔT drifts further out
_JD_ORDINAL = 1721424.5  # Julian day of 0001-01-01 00:00 is this + 1
_BEIJING = 8 / 24


def _sin(degrees: float) -> float:
    return math.sin(math.radians(degrees))


def _delta_t(year: float) -> float:
    """TD − UT in seconds (Espenak and Meeus polynomials; held at the 1986 value before that)."""
    if year < 2005:
        t = max(year, 1986) - 2000
        return 63.86 + 0.3345 * t - 0.060374 * t**2 + 0.0017275 * t**3 + 0.000651814 * t**4 + 0.00002373599 * t**5
    if year < 2050:
        t = year - 2000
        return 62.92 + 0.32217 * t + 0.005589 * t**2
    if year < 2150:
        return -20 + 32 * ((year - 1820) / 100) ** 2 - 0.5628 * (2150 - year)
    return -20 + 32 * ((year - 1820) / 100) ** 2


def _beijing_day(jde: float) -> datetime.date:
    year = 2000 + (jde - 2451545.0) / 365.25
    jd = jde - _delta_t(year) / 86400 + _BEIJING
    return datetime.date.fromordinal(math.floor(jd - _JD_ORDINAL))


def _sun_longitude(jde: float) -> float:
    """Apparent longitude of the sun in degrees (about 0.01° off)."""
    t = (jde - 2451545.0) / 36525
    mean = 280.46646 + 36000.76983 * t + 0.0003032 * t**2
    anomaly = 357.52911 + 35999.05029 * t - 0.0001537 * t**2
    centre = ((1.914602 - 0.004817 * t - 0.000014 * t**2) * _sin(anomaly)
              + (0.019993 - 0.000101 * t) * _sin(2 * anomaly) + 0.000289 * _sin(3 * anomaly))
    omega = 125.04 - 1934.136 * t
    return (mean + centre - 0.00569 - 0.00478 * _sin(omega)) % 360


def _sun_reaches(longitude: float, jde: float) -> float:
    """The moment (JDE) near `jde` when the sun reaches `longitude`."""
    for _ in range(30):
        diff = (longitude - _sun_longitude(jde) + 180) % 360 - 180
        jde += diff * 365.2422 / 360
        if abs(diff) < 1e-7:
            break
    return jde


def _new_moon(k: int) -> float:
    """JDE of new moon number k (k = 0 is the one of 6 January 2000)."""
    t = k / 1236.85
    jde = (2451550.09766 + 29.530588861 * k + 0.00015437 * t**2 - 0.000000150 * t**3 + 0.00000000073 * t**4)
    e = 1 - 0.002516 * t - 0.0000074 * t**2
    m = 2.5534 + 29.10535670 * k - 0.0000014 * t**2 - 0.00000011 * t**3
    mp = 201.5643 + 385.81693528 * k + 0.0107582 * t**2 + 0.00001238 * t**3 - 0.000000058 * t**4
    f = 160.7108 + 390.67050284 * k - 0.0016118 * t**2 - 0.00000227 * t**3 + 0.000000011 * t**4
    omega = 124.7746 - 1.56375588 * k + 0.0020672 * t**2 + 0.00000215 * t**3
    jde += (-0.40720 * _sin(mp) + 0.17241 * e * _sin(m) + 0.01608 * _sin(2 * mp) + 0.01039 * _sin(2 * f)
            + 0.00739 * e * _sin(mp - m) - 0.00514 * e * _sin(mp + m) + 0.00208 * e * e * _sin(2 * m)
            - 0.00111 * _sin(mp - 2 * f) - 0.00057 * _sin(mp + 2 * f) + 0.00056 * e * _sin(2 * mp + m)
            - 0.00042 * _sin(3 * mp) + 0.00042 * e * _sin(m + 2 * f) + 0.00038 * e * _sin(m - 2 * f)
            - 0.00024 * e * _sin(2 * mp - m) - 0.00017 * _sin(omega) - 0.00007 * _sin(mp + 2 * m)
            + 0.00004 * _sin(2 * mp - 2 * f) + 0.00004 * _sin(3 * m) + 0.00003 * _sin(mp + m - 2 * f)
            + 0.00003 * _sin(2 * mp + 2 * f) - 0.00003 * _sin(mp + m + 2 * f) + 0.00003 * _sin(mp - m + 2 * f)
            - 0.00002 * _sin(mp - m - 2 * f) - 0.00002 * _sin(3 * mp + m) + 0.00002 * _sin(4 * mp))
    planets = (
        (0.000325, 299.77 + 0.107408 * k - 0.009173 * t**2), (0.000165, 251.88 + 0.016321 * k),
        (0.000164, 251.83 + 26.651886 * k), (0.000126, 349.42 + 36.412478 * k), (0.000110, 84.66 + 18.206239 * k),
        (0.000062, 141.74 + 53.303771 * k), (0.000060, 207.14 + 2.453732 * k), (0.000056, 154.84 + 7.306860 * k),
        (0.000047, 34.52 + 27.261239 * k), (0.000042, 207.19 + 0.121824 * k), (0.000040, 291.34 + 1.844379 * k),
        (0.000037, 161.72 + 24.198154 * k), (0.000035, 239.56 + 25.513099 * k), (0.000023, 331.55 + 3.592518 * k),
    )
    return jde + sum(size * _sin(angle) for size, angle in planets)


def _jde_of_day(day: datetime.date) -> float:
    """JDE of 00:00 Beijing time on `day`."""
    jd = day.toordinal() + _JD_ORDINAL - _BEIJING
    return jd + _delta_t(day.year) / 86400


def _winter_solstice(year: int) -> datetime.date:
    guess = datetime.date(year, 12, 21).toordinal() + _JD_ORDINAL
    return _beijing_day(_sun_reaches(270.0, guess))


def _has_principal_term(start: datetime.date, end: datetime.date) -> bool:
    """Whether the sun crosses a multiple of 30° between 00:00 on `start` and 00:00 on `end` (Beijing)."""
    return math.floor(_sun_longitude(_jde_of_day(start)) / 30) != math.floor(_sun_longitude(_jde_of_day(end)) / 30)


@lru_cache(maxsize=16)
def _sui(year: int) -> tuple[tuple[datetime.date, int, bool], ...]:
    """The months from month 11 of `year` - 1 up to (not including) month 11 of `year`: (first day, number, leap)."""
    first, last = _winter_solstice(year - 1), _winter_solstice(year)
    k = math.floor((year - 1 + (first.timetuple().tm_yday - 60) / 365.25 - 2000) * 12.3685)
    days = []
    while not days or days[-1] <= last:
        days.append(_beijing_day(_new_moon(k)))
        k += 1
    eleventh = max(day for day in days if day <= first)  # the month holding a solstice is month 11
    next_eleventh = max(day for day in days if day <= last)
    starts = [day for day in days if eleventh <= day <= next_eleventh]
    leap_year = len(starts) - 1 == 13
    months, number, leap_found = [], 11, False
    for i in range(len(starts) - 1):
        leap = (leap_year and not leap_found and i > 0
                and not _has_principal_term(starts[i], starts[i + 1]))
        if leap:
            leap_found = True
        else:
            number = number % 12 + 1 if i > 0 else 11
        months.append((starts[i], number, leap))
    return tuple(months) + ((starts[-1], 11, False),)


def lunar_date(day: datetime.date) -> tuple[int, int, bool]:
    """(month, day, leap) of the lunar date of `day`; ValueError outside FIRST_YEAR to LAST_YEAR."""
    if not FIRST_YEAR <= day.year <= LAST_YEAR:
        raise ValueError(f"no lunar date computed for {day.year}")
    for year in (day.year, day.year + 1):
        months = _sui(year)
        if months[0][0] <= day < months[-1][0]:
            for (start, number, leap), (following, _n, _l) in zip(months, months[1:]):
                if start <= day < following:
                    return number, (day - start).days + 1, leap
    raise ValueError(day)  # not reached: every day lies in one of the two
