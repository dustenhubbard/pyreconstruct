"""Which holiday, if any, the app icon dresses up for on a given day.

Each holiday gets the two weeks before it, the day itself and the week after.
Where two windows overlap (Christmas and New Year's, or St. Patrick's Day and
an early Easter), the nearer holiday wins, and on an exact tie the earlier one
keeps its last day.

Pure date arithmetic so it imports and tests without Qt; the icon files and
the window wiring live in ``gui/utils/app_icon.py``.
"""
from datetime import date

#: Days before a holiday that already show its icon.
DAYS_BEFORE = 14
#: Days after a holiday that still show its icon.
DAYS_AFTER = 7


def easter(year):
    """Western (Gregorian) Easter Sunday: the anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def holiday_dates(year):
    """Every holiday with an icon, mapped to its date in ``year``."""
    return {
        "new_year": date(year, 1, 1),
        "valentines": date(year, 2, 14),
        "st_patricks": date(year, 3, 17),
        "easter": easter(year),
        "independence_day": date(year, 7, 4),
        "halloween": date(year, 10, 31),
        "christmas": date(year, 12, 25),
    }


def holiday_for(day, before=DAYS_BEFORE, after=DAYS_AFTER):
    """The holiday whose window contains ``day``, or None.

    Neighbouring years are checked too, so December can already reach New
    Year's Day and the first days of January can look back.
    """
    candidates = []
    for year in (day.year - 1, day.year, day.year + 1):
        for name, when in holiday_dates(year).items():
            ahead = (when - day).days  # positive: the holiday is still coming
            if -after <= ahead <= before:
                candidates.append((abs(ahead), when, name))
    if not candidates:
        return None
    return min(candidates)[2]
