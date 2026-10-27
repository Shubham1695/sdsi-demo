"""Input data models and validation for the SLA tracker.

All inputs are validated eagerly on load so that malformed data fails fast
with a precise error message instead of producing subtly wrong SLA numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

# Default lifecycle vocabulary. Any other status value is rejected on load.
KNOWN_STATUSES = frozenset({"OPEN", "IN_PROGRESS", "ON_HOLD", "RESOLVED", "CLOSED"})
# Statuses in which the SLA clock is considered running (ON_HOLD pauses it).
CLOCK_RUNNING_STATUSES = frozenset({"OPEN", "IN_PROGRESS"})
# Statuses that terminate the SLA clock permanently.
TERMINAL_STATUSES = frozenset({"RESOLVED", "CLOSED"})


class InputError(ValueError):
    """Raised when an input file violates the expected schema."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise InputError(msg)


def parse_timestamp(value: object, where: str) -> datetime:
    """Parse an ISO-8601 timestamp. Naive datetimes are treated as
    organization-local time; offsets are honoured and normalised away."""
    _require(isinstance(value, str) and value.strip(), f"{where}: timestamp must be a non-empty string")
    text = value.strip()
    try:
        # Support both '...Z' and explicit offsets; Python 3.11+ handles 'Z' natively.
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise InputError(f"{where}: invalid ISO-8601 timestamp {value!r}") from exc
    if dt.tzinfo is not None:
        # Normalise to a naive local reading by stripping the offset after
        # validation. The whole tracker works in org-local wall time; mixed
        # offsets are accepted but interpreted as local wall time shifted.
        dt = dt.replace(tzinfo=None)
    return dt


def parse_date(value: object, where: str) -> date:
    _require(isinstance(value, str), f"{where}: date must be a string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise InputError(f"{where}: invalid ISO date {value!r}") from exc


def parse_hhmm(value: object, where: str) -> time:
    _require(isinstance(value, str), f"{where}: time must be a 'HH:MM' string")
    try:
        return time.fromisoformat(value.strip())
    except ValueError as exc:
        raise InputError(f"{where}: invalid 'HH:MM' time {value!r}") from exc


@dataclass(frozen=True)
class StatusEvent:
    status: str
    at: datetime


@dataclass(frozen=True)
class Ticket:
    id: str
    priority: str
    assignee_group: str
    created_at: datetime
    resolved_at: datetime | None
    status_history: tuple[StatusEvent, ...]


@dataclass(frozen=True)
class BusinessHours:
    """Weekly business calendar: working days (ISO weekday numbers, Mon=1)
    and the daily start/end wall-clock window."""
    days: frozenset[int]
    start: time
    end: time

    def __post_init__(self) -> None:
        _require(self.start < self.end, "business_hours: start must be before end")
        _require(all(1 <= d <= 7 for d in self.days), "business_hours: days must be ISO weekdays 1-7")

    @classmethod
    def from_obj(cls, obj: object) -> "BusinessHours":
        _require(isinstance(obj, dict), "sla_policy: 'business_hours' must be an object")
        days = obj.get("days", [1, 2, 3, 4, 5])
        _require(isinstance(days, list) and all(isinstance(d, int) for d in days),
                 "business_hours: 'days' must be a list of integers (1=Mon..7=Sun)")
        start = parse_hhmm(obj.get("start", "09:00"), "business_hours.start")
        end = parse_hhmm(obj.get("end", "18:00"), "business_hours.end")
        return cls(days=frozenset(days), start=start, end=end)


@dataclass(frozen=True)
class Policy:
    targets_minutes: dict[str, int]
    business_hours: BusinessHours

    @classmethod
    def from_obj(cls, obj: object) -> "Policy":
        _require(isinstance(obj, dict), "sla_policy.json: root must be an object")
        _require("targets_minutes" in obj, "sla_policy: missing 'targets_minutes'")
        raw_targets = obj.get("targets_minutes")
        _require(isinstance(raw_targets, dict), "sla_policy: 'targets_minutes' must be an object")
        targets: dict[str, int] = {}
        for key, value in raw_targets.items():
            _require(isinstance(key, str) and key.strip(), "sla_policy: priority keys must be non-empty strings")
            _require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
                     f"sla_policy: target for {key!r} must be a positive integer (minutes)")
            targets[key.strip().upper()] = value
        _require(targets, "sla_policy: 'targets_minutes' must not be empty")
        return cls(targets_minutes=targets, business_hours=BusinessHours.from_obj(obj.get("business_hours", {})))


@dataclass(frozen=True)
class HolidayCalendar:
    dates: frozenset[date]

    @classmethod
    def from_obj(cls, obj: object) -> "HolidayCalendar":
        _require(isinstance(obj, dict) and isinstance(obj.get("holidays"), list),
                 "holidays.json: root must be an object with a 'holidays' list")
        parsed = [parse_date(d, f"holidays[{i}]") for i, d in enumerate(obj["holidays"])]
        return cls(dates=frozenset(parsed))


def _parse_status_event(obj: object, where: str) -> StatusEvent:
    _require(isinstance(obj, dict), f"{where}: status event must be an object")
    status = obj.get("status")
    _require(isinstance(status, str) and status.strip().upper() in KNOWN_STATUSES,
             f"{where}: unknown status {status!r} (allowed: {sorted(KNOWN_STATUSES)})")
    return StatusEvent(status=status.strip().upper(), at=parse_timestamp(obj.get("at"), f"{where}.at"))


def parse_ticket(obj: object, index: int) -> Ticket:
    where = f"tickets[{index}]"
    _require(isinstance(obj, dict), f"{where}: ticket must be an object")
    tid = obj.get("id")
    _require(isinstance(tid, str) and tid.strip(), f"{where}: 'id' must be a non-empty string")
    priority = obj.get("priority")
    _require(isinstance(priority, str) and priority.strip().upper().startswith("P"),
             f"{where} ({tid}): 'priority' must be a string like 'P1'")
    priority = priority.strip().upper()
    group = obj.get("assignee_group")
    _require(isinstance(group, str) and group.strip(), f"{where} ({tid}): 'assignee_group' must be a non-empty string")
    created = parse_timestamp(obj.get("created_at"), f"{where} ({tid}).created_at")
    resolved_raw = obj.get("resolved_at")
    resolved = parse_timestamp(resolved_raw, f"{where} ({tid}).resolved_at") if resolved_raw is not None else None

    raw_history = obj.get("status_history", [])
    _require(isinstance(raw_history, list), f"{where} ({tid}): 'status_history' must be a list")
    history = [_parse_status_event(e, f"{where} ({tid}).status_history[{i}]") for i, e in enumerate(raw_history)]

    if history:
        # Sort by time; a stable sort keeps same-timestamp events in file order.
        history.sort(key=lambda e: e.at)
        _require(history[0].at <= created,
                 f"{where} ({tid}): first status event predates created_at")
        if resolved is not None:
            _require(history[-1].at <= resolved,
                     f"{where} ({tid}): status events exist after resolved_at")

    return Ticket(id=tid.strip(), priority=priority, assignee_group=group.strip(),
                  created_at=created, resolved_at=resolved, status_history=tuple(history))


@dataclass(frozen=True)
class Dataset:
    tickets: tuple[Ticket, ...]
    policy: Policy
    holidays: HolidayCalendar


def load_json(path: Path) -> object:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise InputError(f"input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    except OSError as exc:
        raise InputError(f"{path}: cannot read file ({exc.strerror})") from exc


def load_dataset(tickets_path: Path, policy_path: Path, holidays_path: Path) -> Dataset:
    policy_obj = load_json(policy_path)
    holidays_obj = load_json(holidays_path)
    tickets_obj = load_json(tickets_path)

    policy = Policy.from_obj(policy_obj)
    holidays = HolidayCalendar.from_obj(holidays_obj)

    # Support both a bare list and {"tickets": [...]}.
    if isinstance(tickets_obj, dict):
        raw_tickets = tickets_obj.get("tickets")
        _require(isinstance(raw_tickets, list), "tickets.json: expected a list or an object with a 'tickets' list")
    elif isinstance(tickets_obj, list):
        raw_tickets = tickets_obj
    else:
        raise InputError("tickets.json: expected a list or an object with a 'tickets' list")

    tickets = [parse_ticket(t, i) for i, t in enumerate(raw_tickets)]

    # Duplicate IDs make per-ticket reporting ambiguous — reject them.
    seen: set[str] = set()
    for t in tickets:
        _require(t.id not in seen, f"duplicate ticket id: {t.id}")
        seen.add(t.id)

    unknown_priorities = sorted({t.priority for t in tickets} - set(policy.targets_minutes))
    if unknown_priorities:
        raise InputError(f"tickets use priorities without an SLA target: {', '.join(unknown_priorities)}")

    return Dataset(tickets=tuple(tickets), policy=policy, holidays=holidays)
