"""Engine-level edge-case matrix.

Each test name describes a scenario from the edge-case analysis; together
they form the executable specification of the SLA semantics.
"""

from __future__ import annotations

from datetime import date, datetime

from sla_tracker.engine import compute_ticket_sla
from sla_tracker.models import BusinessHours, Policy, StatusEvent, Ticket

STD = BusinessHours(days=frozenset({1, 2, 3, 4, 5}), start=datetime(2025, 1, 1, 9).time(),
                    end=datetime(2025, 1, 1, 18).time())
POLICY = Policy(targets_minutes={"P1": 240, "P2": 480, "P3": 1440, "P4": 4320},
                business_hours=STD)
NOW = datetime(2025, 11, 12, 18, 0)


def mk(tid="T", priority="P2", group="G", created=datetime(2025, 11, 3, 9),  # Mon
       resolved=None, history=None):
    return Ticket(id=tid, priority=priority, assignee_group=group, created_at=created,
                  resolved_at=resolved, status_history=tuple(history or []))


def run(ticket, holidays=frozenset()):
    return compute_ticket_sla(ticket, POLICY, holidays, NOW)


# ---------------------------------------------------------------- M1 basics

def test_full_window_ticket_meeting_target():
    # Mon 09:00 -> Mon 17:00 = 480 min = P2 target exactly: no breach.
    t = mk(resolved=datetime(2025, 11, 3, 17, 0))
    r = run(t)
    assert r.elapsed_business_minutes == 480
    assert r.is_breached is False
    assert r.due_by == datetime(2025, 11, 3, 17, 0)


def test_one_minute_over_is_breach():
    # P1 target 240: resolved at 13:01 → 241 elapsed, breach 1 min.
    t = mk(priority="P1", resolved=datetime(2025, 11, 3, 13, 1))
    r = run(t)
    assert r.is_breached is True
    assert r.breach_minutes == 1


def test_created_outside_hours_rolls_to_next_business_instant():
    # Created Sat 13:00 -> clock starts Mon 09:00; 60 min run to Mon 10:00.
    # P2 due-by = Mon 09:00 + 480 business min = Mon 17:00 (fits in one day).
    t = mk(created=datetime(2025, 11, 8, 13, 0),
           resolved=datetime(2025, 11, 10, 10, 0))
    r = run(t)
    assert r.elapsed_business_minutes == 60
    assert r.due_by == datetime(2025, 11, 10, 17, 0)


def test_created_after_hours_rolls_to_next_morning():
    # Created Mon 18:30 -> clock starts Tue 09:00
    t = mk(created=datetime(2025, 11, 3, 18, 30),
           resolved=datetime(2025, 11, 4, 9, 30))
    r = run(t)
    assert r.elapsed_business_minutes == 30


def test_resolution_outside_hours_counts_to_window_close():
    # Resolved Sat 14:00: last business instant is Fri 18:00
    t = mk(created=datetime(2025, 11, 5, 16, 0),  # Wed
           resolved=datetime(2025, 11, 8, 14, 0))
    r = run(t)
    # Wed 16-18 (120) + Thu 540 + Fri 540 = 1200
    assert r.elapsed_business_minutes == 1200


def test_unresolved_ticket_counts_to_now():
    t = mk(created=datetime(2025, 11, 3, 9, 0), resolved=None)
    r = run(t)  # NOW = Nov 12 18:00
    # Mon-Fri 3-7 Nov: 5*540=2700; Mon-Wed 10-12 Nov: 3*540=1620; total 4320
    assert r.elapsed_business_minutes == 4320
    assert r.is_resolved is False


# ---------------------------------------------------------------- M2 holidays

def test_holiday_excluded():
    # Tue 2025-11-11 holiday: Mon 09:00 + 540 (Mon) + 0 (Tue) + 540 (Wed)
    t = mk(created=datetime(2025, 11, 10, 9, 0),
           resolved=datetime(2025, 11, 12, 18, 0),
           history=[StatusEvent("OPEN", datetime(2025, 11, 10, 9, 0))])
    r = run(t, holidays={date(2025, 11, 11)})
    assert r.elapsed_business_minutes == 1080


def test_holiday_on_weekend_not_double_counted():
    # Sat 2025-11-15 is already non-working; listing it as a holiday must not
    # change anything.
    t = mk(created=datetime(2025, 11, 14, 9, 0),  # Fri
           resolved=datetime(2025, 11, 17, 9, 0))  # Mon
    r_plain = run(t)
    r_with = run(t, holidays={date(2025, 11, 15)})
    assert r_plain.elapsed_business_minutes == r_with.elapsed_business_minutes == 540


def test_p4_target_spans_eight_business_days():
    # 4320 = 8*540 exactly: Mon Nov 3 09:00 + 8 business days lands at the
    # close of business on the 8th day (Wed Nov 12 18:00).
    t = mk(priority="P4", created=datetime(2025, 11, 3, 9, 0))
    r = run(t)
    assert r.due_by == datetime(2025, 11, 12, 18, 0)


# ---------------------------------------------------------------- M3 holds

def test_hold_pauses_clock():
    # Mon 09:00-14:00 run (300), hold Mon 14:00 -> Tue 09:30, run Tue 09:30-11:00 (90)
    t = mk(created=datetime(2025, 11, 3, 9, 0),
           resolved=datetime(2025, 11, 4, 11, 0),
           history=[
               StatusEvent("OPEN", datetime(2025, 11, 3, 9, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 3, 14, 0)),
               StatusEvent("IN_PROGRESS", datetime(2025, 11, 4, 9, 30)),
               StatusEvent("RESOLVED", datetime(2025, 11, 4, 11, 0)),
           ])
    r = run(t)
    assert r.elapsed_business_minutes == 390


def test_hold_spanning_weekend_and_holiday():
    # Hold from Fri 14:00 to next Wed 10:00 spans a weekend; holiday Tue.
    t = mk(created=datetime(2025, 11, 7, 9, 0),  # Fri
           resolved=datetime(2025, 11, 13, 12, 0),
           history=[
               StatusEvent("OPEN", datetime(2025, 11, 7, 9, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 7, 14, 0)),
               StatusEvent("IN_PROGRESS", datetime(2025, 11, 12, 10, 0)),
               StatusEvent("RESOLVED", datetime(2025, 11, 13, 12, 0)),
           ])
    r = run(t, holidays={date(2025, 11, 11)})
    # Fri 9-14 (300) + Wed 10-18 (480) + Thu 9-12 (180) = 960
    assert r.elapsed_business_minutes == 960


def test_hold_outside_business_hours_pauses_nothing():
    # Hold declared 18:30 (after hours) to 08:00 next day: zero business pause.
    t = mk(created=datetime(2025, 11, 3, 9, 0),
           resolved=datetime(2025, 11, 3, 17, 0),
           history=[
               StatusEvent("OPEN", datetime(2025, 11, 3, 9, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 3, 18, 30)),
               StatusEvent("IN_PROGRESS", datetime(2025, 11, 4, 8, 0)),
               StatusEvent("RESOLVED", datetime(2025, 11, 3, 17, 0)),
           ])
    r = run(t)
    assert r.elapsed_business_minutes == 480  # full 09:00-17:00


def test_multiple_holds_accumulate():
    t = mk(created=datetime(2025, 11, 3, 9, 0),
           resolved=datetime(2025, 11, 4, 18, 0),
           history=[
               StatusEvent("OPEN", datetime(2025, 11, 3, 9, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 3, 10, 0)),
               StatusEvent("IN_PROGRESS", datetime(2025, 11, 3, 11, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 3, 12, 0)),
               StatusEvent("IN_PROGRESS", datetime(2025, 11, 3, 13, 0)),
               StatusEvent("RESOLVED", datetime(2025, 11, 4, 18, 0)),
           ])
    r = run(t)
    # Mon: 540 - 120 held = 420; Tue: full 540 -> 960
    assert r.elapsed_business_minutes == 960


def test_duplicate_hold_events_idempotent():
    # Two ON_HOLD in a row then one exit: pause counted once.
    # Elapsed: 09:00-17:00 = 480 minus 10:00-12:00 hold (120) = 360.
    t = mk(created=datetime(2025, 11, 3, 9, 0),
           resolved=datetime(2025, 11, 3, 17, 0),
           history=[
               StatusEvent("OPEN", datetime(2025, 11, 3, 9, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 3, 10, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 3, 10, 30)),
               StatusEvent("IN_PROGRESS", datetime(2025, 11, 3, 12, 0)),
               StatusEvent("RESOLVED", datetime(2025, 11, 3, 17, 0)),
           ])
    r = run(t)
    assert r.elapsed_business_minutes == 360


def test_still_on_hold_counts_to_hold_start():
    # Ticket on hold with no exit: clock stopped at hold start even as of NOW.
    t = mk(created=datetime(2025, 11, 3, 9, 0),
           resolved=None,
           history=[
               StatusEvent("OPEN", datetime(2025, 11, 3, 9, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 3, 12, 0)),
           ])
    r = run(t)
    assert r.elapsed_business_minutes == 180
    assert r.currently_on_hold is True


def test_hold_pushes_due_by_out():
    # P2 target 480. Mon 09:00-14:00 run (300), hold Mon 14:00 -> Tue 09:30.
    # Remaining 180 accrue from Tue 09:30 -> due-by Tue 12:30.
    t = mk(created=datetime(2025, 11, 3, 9, 0),
           resolved=None,
           history=[
               StatusEvent("OPEN", datetime(2025, 11, 3, 9, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 3, 14, 0)),
               StatusEvent("IN_PROGRESS", datetime(2025, 11, 4, 9, 30)),
           ])
    r = run(t)
    assert r.due_by == datetime(2025, 11, 4, 12, 30)


# ---------------------------------------------------------------- robustness

def test_status_events_sorted_out_of_order_input():
    # History arrives unsorted; engine must normalize.
    t = mk(created=datetime(2025, 11, 3, 9, 0),
           resolved=datetime(2025, 11, 3, 15, 0),
           history=[
               StatusEvent("RESOLVED", datetime(2025, 11, 3, 15, 0)),
               StatusEvent("ON_HOLD", datetime(2025, 11, 3, 11, 0)),
               StatusEvent("OPEN", datetime(2025, 11, 3, 9, 0)),
               StatusEvent("IN_PROGRESS", datetime(2025, 11, 3, 12, 0)),
           ])
    r = run(t)
    # 09:00-15:00 = 360, minus the 11:00-12:00 hold (60) = 300
    assert r.elapsed_business_minutes == 300


def test_event_before_creation_is_ignored():
    t = mk(created=datetime(2025, 11, 3, 9, 0),
           resolved=datetime(2025, 11, 3, 13, 0),
           history=[
               StatusEvent("ON_HOLD", datetime(2025, 11, 2, 9, 0)),  # pre-creation
               StatusEvent("OPEN", datetime(2025, 11, 3, 9, 0)),
               StatusEvent("RESOLVED", datetime(2025, 11, 3, 13, 0)),
           ])
    r = run(t)
    assert r.elapsed_business_minutes == 240


def test_no_history_still_computes():
    # Status history optional: clock runs created -> resolved.
    t = mk(created=datetime(2025, 11, 3, 9, 0),
           resolved=datetime(2025, 11, 3, 11, 0))
    r = run(t)
    assert r.elapsed_business_minutes == 120


def test_breach_recorded_even_if_resolved_late():
    # P1 target 240: resolved Mon 14:00 → 300 elapsed, breach 60.
    t = mk(priority="P1", created=datetime(2025, 11, 3, 9, 0),
           resolved=datetime(2025, 11, 3, 14, 0))
    r = run(t)
    assert r.is_breached is True
    assert r.breach_minutes == 60


def test_zero_target_not_configurable_to_zero_is_rejected():
    import pytest
    from sla_tracker.models import InputError, Policy
    with pytest.raises(InputError):
        Policy.from_obj({"targets_minutes": {"P1": 0}})
    with pytest.raises(InputError):
        Policy.from_obj({"targets_minutes": {"P1": "240"}})
