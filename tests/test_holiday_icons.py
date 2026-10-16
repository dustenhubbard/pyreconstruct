"""Holiday app icons: which days get one, and that every holiday ships one.

The window shows a holiday's icon for the two weeks before it, the day itself
and the week after. Overlapping windows (Christmas and New Year's) go to the
nearer holiday, and on a tie the earlier holiday keeps its last day.
"""
from datetime import date

import pytest

from PyReconstruct.modules.backend.holidays import (
    DAYS_AFTER,
    DAYS_BEFORE,
    easter,
    holiday_dates,
    holiday_for,
)


@pytest.mark.parametrize("year, expected", [
    (2024, date(2024, 3, 31)),
    (2025, date(2025, 4, 20)),
    (2026, date(2026, 4, 5)),
    (2027, date(2027, 3, 28)),
    (2035, date(2035, 3, 25)),
    (2038, date(2038, 4, 25)),
])
def test_easter_matches_the_published_dates(year, expected):
    assert easter(year) == expected


def test_the_window_is_two_weeks_before_and_one_week_after():
    assert (DAYS_BEFORE, DAYS_AFTER) == (14, 7)
    assert holiday_for(date(2026, 10, 16)) is None
    assert holiday_for(date(2026, 10, 17)) == "halloween"
    assert holiday_for(date(2026, 10, 31)) == "halloween"
    assert holiday_for(date(2026, 11, 7)) == "halloween"
    assert holiday_for(date(2026, 11, 8)) is None


def test_valentines_starts_two_weeks_early():
    assert holiday_for(date(2027, 1, 30)) is None
    assert holiday_for(date(2027, 1, 31)) == "valentines"


def test_an_ordinary_day_has_no_holiday():
    assert holiday_for(date(2026, 9, 1)) is None
    assert holiday_for(date(2026, 6, 15)) is None


def test_christmas_hands_over_to_new_years_at_the_midpoint():
    assert holiday_for(date(2026, 12, 10)) is None
    assert holiday_for(date(2026, 12, 11)) == "christmas"
    assert holiday_for(date(2026, 12, 18)) == "christmas"
    assert holiday_for(date(2026, 12, 28)) == "christmas"
    assert holiday_for(date(2026, 12, 29)) == "new_year"
    assert holiday_for(date(2027, 1, 8)) == "new_year"
    assert holiday_for(date(2027, 1, 9)) is None


def test_new_years_window_reaches_back_across_the_year_boundary():
    assert holiday_for(date(2026, 12, 31)) == "new_year"


def test_an_early_easter_shares_the_overlap_with_st_patricks():
    # Easter 2035 is March 25: March 21 is four days from both.
    assert holiday_for(date(2035, 3, 21)) == "st_patricks"
    assert holiday_for(date(2035, 3, 22)) == "easter"


def test_every_year_lists_seven_distinct_holidays():
    dates = holiday_dates(2026)
    assert len(dates) == 7
    assert len(set(dates.values())) == 7


def test_every_holiday_ships_an_icon_for_both_builds():
    from PyReconstruct.modules.constants import img_dir
    from pathlib import Path

    root = Path(img_dir) / "holidays"
    for name in holiday_dates(2026):
        for flavor in ("stable", "dev"):
            folder = root / name / flavor
            sizes = sorted(int(p.stem.split("-")[1]) for p in folder.glob("icon-*.png"))
            assert sizes == [16, 24, 32, 48, 64, 128, 256], (name, flavor, sizes)
            assert (folder / "dock-256.png").is_file(), (name, flavor)


@pytest.mark.gui
def test_the_window_icon_follows_the_date_and_the_build(qapp, monkeypatch):
    from PyReconstruct.modules.gui.utils import app_icon

    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    assert app_icon.holiday_icon_dir(date(2026, 9, 1)) is None
    folder = app_icon.holiday_icon_dir(date(2026, 10, 31))
    assert folder.parts[-2:] == ("halloween", "stable")
    assert not app_icon.window_icon(date(2026, 10, 31)).isNull()

    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    assert app_icon.holiday_icon_dir(date(2026, 12, 25)).parts[-2:] == ("christmas", "dev")


@pytest.mark.gui
def test_an_ordinary_day_keeps_the_regular_icon(qapp):
    from PySide6.QtGui import QIcon, QPixmap
    from PyReconstruct.modules.constants import icon_path
    from PyReconstruct.modules.gui.utils import app_icon

    regular = QIcon(QPixmap(icon_path))
    icon = app_icon.window_icon(date(2026, 9, 1))
    assert icon.availableSizes() == regular.availableSizes()
