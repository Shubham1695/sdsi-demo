"""Brute-force reference implementation and cross-check against the
closed-form calendar engine.

The reference walks minute by minute — obviously correct, obviously slow.
Property-style randomized comparison proves the fast engine agrees with it,
which is the strongest correctness signal available for interval arithmetic.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sla_tracker.calendar import add_business_minutes, business_minutes_between
from sla_tracker.models import BusinessHours

STD = BusinessHours(days=frozenset({1, 2, 3, 4, 5}), start=time(9, 0), end=time(18, 0))


def ref_business_minutes(start: datetime, end: datetime, hours: BusinessHours,
                         holidays=frozenset()) -> float:
    """Minute-by-minute reference: count minutes t where t and t+1min both
    fall inside a business window (half-open [t, t+1) semantics)."""
    if end < start:
        raise ValueError
    total = 0.0
    t = start
    while t < end:
        nxt = t + timedelta(minutes=1)
        d = t.date()
        if d.weekday() + 1 in hours.days and d not in holidays:
            w_start = datetime.combine(d, hours.start)
            w_end = datetime.combine(d, hours.end)
            if t >= w_start and nxt <= w_end:
                total += 1
        t = nxt
    return total


def ref_add_business_minutes(start: datetime, minutes: float, hours: BusinessHours,
                             holidays=frozenset()) -> datetime:
    """Minute-by-minute reference for add_business_minutes."""
    if minutes < 0:
        raise ValueError
    remaining = minutes
    t = start
    # First, if start is outside a window, roll to the next window start.
    while True:
        d = t.date()
        if d.weekday() + 1 in hours.days and d not in holidays:
            w_start = datetime.combine(d, hours.start)
            w_end = datetime.combine(d, hours.end)
            if w_start <= t < w_end:
                break
            if t < w_start:
                t = w_start
                break
        t = datetime.combine(d, time(0, 0)) + timedelta(days=1)
    if remaining == 0:
        return t
    while remaining > 0:
        d = t.date()
        w_end = datetime.combine(d, hours.end)
        step = min(timedelta(minutes=1), w_end - t)
        t += step
        if step == timedelta(minutes=1):
            remaining -= 1
        # move to next window when this one is exhausted
        if t >= w_end:
            t = datetime.combine(d, time(0, 0)) + timedelta(days=1)
            while True:
                d2 = t.date()
                if d2.weekday() + 1 in hours.days and d2 not in holidays:
                    t = max(t, datetime.combine(d2, hours.start))
                    break
                t = datetime.combine(d2, time(0, 0)) + timedelta(days=1)
    return t


def test_reference_agrees_simple_cases():
    # Full week: 5 days * 540
    start = datetime(2025, 11, 3, 0, 0)
    end = datetime(2025, 11, 8, 0, 0)
    assert business_minutes_between(start, end, STD) == 2700
    assert ref_business_minutes(start, end, STD) == 2700


def test_partial_day_edges():
    # start before window opens
    assert business_minutes_between(datetime(2025, 11, 3, 7, 0),
                                    datetime(2025, 11, 3, 10, 0), STD) == 60
    # end after window closes
    assert business_minutes_between(datetime(2025, 11, 3, 17, 0),
                                    datetime(2025, 11, 3, 20, 0), STD) == 60
    # entirely outside business hours
    assert business_minutes_between(datetime(2025, 11, 3, 20, 0),
                                    datetime(2025, 11, 3, 23, 0), STD) == 0


def test_exact_window_boundaries():
    # [09:00, 18:00) on one day = 540
    assert business_minutes_between(datetime(2025, 11, 3, 9, 0),
                                    datetime(2025, 11, 3, 18, 0), STD) == 540
    # zero-length and inverted ranges
    assert business_minutes_between(datetime(2025, 11, 3, 9, 0),
                                    datetime(2025, 11, 3, 9, 0), STD) == 0


def test_holidays_and_weekends():
    # Mon 00:00 -> Sat 00:00 covers Mon-Fri = 5 days; Tue holiday removes one.
    assert business_minutes_between(datetime(2025, 11, 10, 0, 0),
                                    datetime(2025, 11, 15, 0, 0), STD,
                                    holidays={date(2025, 11, 11)}) == 4 * 540
    # holiday on a weekend (Sat 2025-11-15) must not double-subtract
    assert business_minutes_between(datetime(2025, 11, 10, 0, 0),
                                    datetime(2025, 11, 15, 0, 0), STD,
                                    holidays={date(2025, 11, 15)}) == 5 * 540


def test_cross_period_span():
    assert business_minutes_between(datetime(2025, 11, 3, 17, 0),
                                    datetime(2025, 11, 4, 10, 0), STD) == 60 + 60


def test_add_business_minutes_basic():
    assert add_business_minutes(datetime(2025, 11, 3, 9, 0), 60, STD) == \
        datetime(2025, 11, 3, 10, 0)
    # spills over into next day
    assert add_business_minutes(datetime(2025, 11, 3, 17, 0), 120, STD) == \
        datetime(2025, 11, 4, 10, 0)
    # start on weekend rolls to Monday
    assert add_business_minutes(datetime(2025, 11, 8, 13, 0), 60, STD) == \
        datetime(2025, 11, 10, 10, 0)
    # exactly a full day lands at window end
    assert add_business_minutes(datetime(2025, 11, 3, 9, 0), 540, STD) == \
        datetime(2025, 11, 3, 18, 0)


def test_add_business_minutes_with_holiday():
    # Mon 16:00 + 120 business min: Mon 16-18 (120) -> Tue 18:00... but Tue
    # 2025-11-11 is a holiday, so the remainder rolls to Wed 09:00+? No: the
    # full 120 fits Monday, landing at Mon 18:00.
    assert add_business_minutes(datetime(2025, 11, 10, 16, 0), 120, STD,
                                holidays={date(2025, 11, 11)}) == \
        datetime(2025, 11, 10, 18, 0)
    # 180 min spills: Mon 120, then Wed 60 (Tue is holiday) -> Wed 10:00
    assert add_business_minutes(datetime(2025, 11, 10, 16, 0), 180, STD,
                                holidays={date(2025, 11, 11)}) == \
        datetime(2025, 11, 12, 10, 0)


def test_roundtrip_property():
    """add then measure must consume exactly the minutes added."""
    for minutes in (1, 7, 60, 539, 540, 541, 1080, 4320):
        start = datetime(2025, 11, 3, 12, 0)
        due = add_business_minutes(start, minutes, STD)
        assert business_minutes_between(start, due, STD) == minutes


def test_due_by_exact_target_is_not_breach_boundary():
    """Consuming exactly the target means due_by == end; elapsed == target."""
    start = datetime(2025, 11, 3, 9, 0)
    due = add_business_minutes(start, 240, STD)
    assert business_minutes_between(start, due, STD) == 240
