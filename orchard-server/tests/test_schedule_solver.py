"""Pure tests for app.agent.schedule_solver — no DB."""
from __future__ import annotations

from datetime import date

from app.agent.schedule_solver import TreePhenology, next_due, next_valid_date


def test_unconstrained():
    out = next_due(
        after=date(2026, 1, 1),
        interval_days=30,
        valid_months=None,
        biological_anchor=None,
        anchor_offset_days=None,
        phenology=TreePhenology(),
    )
    assert out.date == date(2026, 1, 31)
    assert out.skipped is False
    assert out.window_closes_on is None


def test_in_window_valid_months():
    out = next_due(
        after=date(2026, 5, 1),
        interval_days=30,
        valid_months=[3, 4, 5],
        biological_anchor=None,
        anchor_offset_days=None,
        phenology=TreePhenology(),
    )
    assert out.date == date(2026, 5, 31)
    assert out.skipped is False
    assert out.window_closes_on == date(2026, 5, 31)


def test_clamp_forward_to_next_valid_month():
    out = next_due(
        after=date(2026, 5, 20),
        interval_days=30,
        valid_months=[3, 4, 5],
        biological_anchor=None,
        anchor_offset_days=None,
        phenology=TreePhenology(),
    )
    assert out.date == date(2027, 3, 1)
    assert out.skipped is False


def test_next_valid_date_rolls_expired_window_across_year():
    assert next_valid_date(date(2026, 6, 15), [3, 4, 5]) == date(2027, 3, 1)


def test_next_valid_date_keeps_today_when_month_is_valid():
    assert next_valid_date(date(2026, 4, 15), [3, 4, 5]) == date(2026, 4, 15)


def test_safety_allow_before_cutoff():
    out = next_due(
        after=date(2026, 7, 1),
        interval_days=30,
        valid_months=None,
        biological_anchor="flowering",
        anchor_offset_days=-30,
        phenology=TreePhenology(flowering_months=(9,), harvest_months=(11,)),
    )
    assert out.date == date(2026, 7, 31)
    assert out.skipped is False


def test_safety_skip_inside_cutoff_window():
    out = next_due(
        after=date(2026, 7, 15),
        interval_days=30,
        valid_months=None,
        biological_anchor="flowering",
        anchor_offset_days=-30,
        phenology=TreePhenology(flowering_months=(9,), harvest_months=(11,)),
    )
    assert out.skipped is True
    assert out.date == date(2026, 11, 1)
    assert out.reason is not None
    assert "flowering" in out.reason.lower() or "cutoff" in out.reason.lower()


def test_missing_phenology_no_skip():
    out = next_due(
        after=date(2026, 7, 15),
        interval_days=30,
        valid_months=None,
        biological_anchor="flowering",
        anchor_offset_days=-30,
        phenology=TreePhenology(flowering_months=(), harvest_months=(11,)),
    )
    assert out.skipped is False
    assert out.date == date(2026, 8, 14)


def test_empty_valid_months_no_clamp():
    out = next_due(
        after=date(2026, 5, 20),
        interval_days=30,
        valid_months=[],
        biological_anchor=None,
        anchor_offset_days=None,
        phenology=TreePhenology(),
    )
    assert out.date == date(2026, 6, 19)
    assert out.window_closes_on is None


def test_twice_flowering_skip_after_september_cutoff():
    """Twice-yearly flowering [Mar, Sep], harvest [Jun, Dec], offset -30.

    Last done 2026-07-15 + 30d → candidate 2026-08-14. September flowering
    cutoff is Aug 2 (Sep 1 minus 30d); resume is Dec 1 (next harvest after
    cutoff). Aug 14 falls in [Aug 2, Dec 1) so the task skips to Dec 1.
    """
    out = next_due(
        after=date(2026, 7, 15),
        interval_days=30,
        valid_months=None,
        biological_anchor="flowering",
        anchor_offset_days=-30,
        phenology=TreePhenology(
            flowering_months=(3, 9),
            harvest_months=(6, 12),
        ),
    )
    assert out.skipped is True
    assert out.date == date(2026, 12, 1)

