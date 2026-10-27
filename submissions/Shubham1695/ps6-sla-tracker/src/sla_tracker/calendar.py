"""Closed-form business-hours calendar arithmetic.

All functions here are pure: no I/O, no globals, no clock reads. The module
answers two questions in O(#days-in-range) instead of O(#minutes):

* ``business_minutes_between`` — how many business minutes elapsed in a span?
* ``add_business_minutes``    — where does a span of business minutes end?

Both are built on the same day-window logic so they can never disagree.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .models import BusinessHours

_FULL_DAY_CACHE: dict[tuple[frozenset[int], time, time], float] = {}


def _minutes(t: time) -> float:
    return t.hour * 60 + t.minute


def full_day_minutes(hours: BusinessHours) -> float:
    """Business minutes contained in one fully-working day (cached)."""
    key = (hours.days, hours.start, hours.end)
    value = _FULL_DAY_CACHE.get(key)
    if value is None:
        value = _minutes(hours.end) - _minutes(hours.start)
        _FULL_DAY_CACHE[key] = value
    return value


def iter_business_days(start: date, end: date, hours: BusinessHours):
    """Yield each calendar day in ``[start, end]`` that is a working day
    (weekday per the calendar; holidays are handled by callers)."""
    day = start
    while day <= end:
        if day.weekday() + 1 in hours.days:
            yield day
        day += timedelta(days=1)


def _segment_minutes(day: date, hours: BusinessHours, lo: datetime, hi: datetime) -> float:
    """Business minutes of the day-window of *day* clipped to ``[lo, hi]``."""
    window_start = datetime.combine(day, hours.start)
    window_end = datetime.combine(day, hours.end)
    seg_lo = max(lo, window_start)
    seg_hi = min(hi, window_end)
    if seg_lo >= seg_hi:
        return 0.0
    return (seg_hi - seg_lo).total_seconds() / 60.0


def business_minutes_between(start: datetime, end: datetime, hours: BusinessHours,
                             holidays=frozenset()) -> float:
    """Business minutes in ``[start, end)`` (start inclusive, end exclusive).

    Non-working days (weekends per the calendar and dates in *holidays*)
    contribute zero. Raises ValueError if end < start.

    O(#days in range) — no minute-by-minute stepping.
    """
    if end < start:
        raise ValueError("business_minutes_between: end must not precede start")
    if end == start:
        return 0.0

    first_day = start.date()
    last_day = end.date()

    # Fast path: whole days strictly between the two endpoint days, plus the
    # clipped first and last days.
    inner_weekdays = sum(1 for _ in iter_business_days(first_day + timedelta(days=1),
                                                       last_day - timedelta(days=1),
                                                       hours))
    inner_holidays = sum(1 for d in holidays
                         if first_day < d < last_day and d.weekday() + 1 in hours.days)
    total = (inner_weekdays - inner_holidays) * full_day_minutes(hours)

    # Clipped boundary days (the same day handled once if start/end share it).
    boundary_days = {first_day, last_day}
    for day in boundary_days:
        if day.weekday() + 1 in hours.days and day not in holidays:
            total += _segment_minutes(day, hours, start, end)
    return total


def add_business_minutes(start: datetime, minutes: float, hours: BusinessHours,
                         holidays=frozenset()) -> datetime:
    """The wall-clock instant when *minutes* of business time have accrued
    from *start*. If *start* is outside the business window, the clock is
    deemed to start at the next business instant.

    Raises ValueError for negative *minutes*.
    """
    if minutes < 0:
        raise ValueError("add_business_minutes: minutes must be non-negative")

    day = start.date()
    remaining = minutes
    while True:
        if day.weekday() + 1 in hours.days and day not in holidays:
            window_start = datetime.combine(day, hours.start)
            window_end = datetime.combine(day, hours.end)
            seg_start = max(start, window_start)
            if seg_start < window_end:
                if remaining == 0:
                    return seg_start
                avail = (window_end - seg_start).total_seconds() / 60.0
                if remaining <= avail:
                    return seg_start + timedelta(minutes=remaining)
                remaining -= avail
        day += timedelta(days=1)
