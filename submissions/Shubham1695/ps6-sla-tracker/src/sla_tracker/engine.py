"""SLA computation: elapsed business minutes, due-by, and breach detection.

The engine is a pure function of (ticket, policy, holidays, now). Two
invariants drive the design:

1. **One clock model.** Elapsed and due-by both go through the same calendar
   primitives, so a ticket that consumed exactly its target is never
   simultaneously "not breached" and "past due".
2. **The clock runs when the ticket's latest status says it runs.** ON_HOLD
   pauses the clock; RESOLVED/CLOSED stop it permanently.

Due-by semantics — the deadline is the wall-clock instant at which the clock
*would* accrue the target minutes. Holds push the deadline out, so the due-by
instant is found by a fixpoint iteration: start from ``effective_start +
target`` business minutes, then repeatedly add the business minutes of any
hold that falls before the current deadline until it stops moving. This is
exact whether or not the ticket has already consumed its target, and holds
that begin exactly at the deadline don't shift it (half-open intervals).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .calendar import add_business_minutes, business_minutes_between
from .models import CLOCK_RUNNING_STATUSES, BusinessHours, Policy, Ticket


def _active_end(ticket: Ticket, now: datetime) -> datetime:
    """The wall-clock instant up to which the SLA clock has run."""
    return ticket.resolved_at if ticket.resolved_at is not None else now


def _hold_intervals(history, created_at: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Wall-clock intervals during which the ticket was ON_HOLD, derived from
    the status history (sorted defensively — the loader normally does this,
    but direct construction bypasses it).

    Robustness rules:
    * a hold without a matching exit runs until *end* (data cutoff);
    * duplicate ON_HOLD events are idempotent (the open hold simply extends);
    * hold intervals are clamped to ``[created_at, end]``;
    * an exit event with no matching ON_HOLD is ignored.
    """
    holds: list[tuple[datetime, datetime]] = []
    hold_open_since: datetime | None = None
    last_status: str | None = None

    for event in sorted(history, key=lambda e: e.at):
        if event.at < created_at or event.at > end:
            continue
        if event.status == "ON_HOLD":
            if hold_open_since is None:
                hold_open_since = event.at
        elif event.status in CLOCK_RUNNING_STATUSES and hold_open_since is not None:
            holds.append((hold_open_since, event.at))
            hold_open_since = None
        last_status = event.status

    if hold_open_since is not None:  # still on hold at the cutoff
        holds.append((hold_open_since, end))
    return holds


def _subtract_holds(running: list[tuple[datetime, datetime]],
                    holds: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Subtract hold intervals from clock-running intervals (both sorted,
    non-overlapping by construction)."""
    result: list[tuple[datetime, datetime]] = []
    for lo, hi in running:
        pieces: list[tuple[datetime, datetime]] = [(lo, hi)]
        for hlo, hhi in holds:
            next_pieces: list[tuple[datetime, datetime]] = []
            for plo, phi in pieces:
                if hhi <= plo or hlo >= phi:
                    next_pieces.append((plo, phi))
                    continue
                if hlo > plo:
                    next_pieces.append((plo, hlo))
                if hhi < phi:
                    next_pieces.append((hhi, phi))
            pieces = next_pieces
        result.extend(pieces)
    return result


def _due_by_instant(effective_start: datetime, target: float, holds: list[tuple[datetime, datetime]],
                    hours: BusinessHours, holidays: frozenset) -> datetime:
    """Fixpoint deadline: the wall-clock instant at which a clock starting at
    *effective_start* accrues *target* business minutes, with every hold that
    falls before the deadline pushing it out by the hold's business minutes."""
    due_by = add_business_minutes(effective_start, target, hours, holidays)
    for _ in range(len(holds) + 1):  # each pass can only absorb one more hold region
        shifted = 0.0
        for lo, hi in holds:
            lo2, hi2 = max(lo, effective_start), min(hi, due_by)
            if lo2 < hi2:  # hold overlaps the accrual window; else irrelevant
                shifted += business_minutes_between(lo2, hi2, hours, holidays)
        candidate = add_business_minutes(effective_start, target + shifted, hours, holidays)
        if candidate == due_by:
            return due_by
        due_by = candidate
    return due_by


def _is_on_hold_at(history, at: datetime) -> bool:
    """Whether the ticket's latest known status at instant *at* is ON_HOLD."""
    last: str | None = None
    for event in sorted(history, key=lambda e: e.at):
        if event.at > at:
            break
        last = event.status
    return last == "ON_HOLD"


@dataclass(frozen=True)
class TicketSLA:
    ticket_id: str
    priority: str
    assignee_group: str
    target_minutes: float
    elapsed_business_minutes: float
    due_by: datetime
    is_breached: bool
    breach_minutes: float
    is_resolved: bool
    currently_on_hold: bool

    @property
    def remaining_minutes(self) -> float:
        return max(0.0, self.target_minutes - self.elapsed_business_minutes)


def compute_ticket_sla(ticket: Ticket, policy: Policy, holidays: frozenset,
                       now: datetime) -> TicketSLA:
    """Compute the SLA record for one ticket.

    *now* is the evaluation cutoff: for unresolved tickets the clock is read
    as of *now* (paused if the ticket is on hold at that moment).
    """
    hours = policy.business_hours
    target = float(policy.targets_minutes[ticket.priority])

    end = _active_end(ticket, now)
    holds = _hold_intervals(ticket.status_history, ticket.created_at, end)

    running = _subtract_holds([(ticket.created_at, end)], holds)
    elapsed = sum(business_minutes_between(lo, hi, hours, holidays) for lo, hi in running)

    # Effective start = first instant the clock actually ran (next business
    # instant at/after creation) — found by advancing zero minutes.
    effective_start = add_business_minutes(ticket.created_at, 0.0, hours, holidays)
    due_by = _due_by_instant(effective_start, target, holds, hours, holidays)

    breach_minutes = max(0.0, elapsed - target)
    # A resolved ticket can still be breached (resolved late); an unresolved
    # ticket breaches when elapsed has passed the target as of *now*.
    is_breached = breach_minutes > 0.0

    return TicketSLA(
        ticket_id=ticket.id,
        priority=ticket.priority,
        assignee_group=ticket.assignee_group,
        target_minutes=target,
        elapsed_business_minutes=elapsed,
        due_by=due_by,
        is_breached=is_breached,
        breach_minutes=breach_minutes,
        is_resolved=ticket.resolved_at is not None,
        currently_on_hold=_is_on_hold_at(ticket.status_history, end),
    )


def compute_all(dataset, now: datetime) -> list[TicketSLA]:
    return [compute_ticket_sla(t, dataset.policy, dataset.holidays.dates, now)
            for t in dataset.tickets]
