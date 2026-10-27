"""M5 aggregation: breach percentages per priority and per assignee group."""

from __future__ import annotations

from dataclasses import dataclass

from .engine import TicketSLA


@dataclass(frozen=True)
class GroupStats:
    key: str
    total: int
    breached: int
    breach_pct: float

    def as_dict(self) -> dict:
        return {"key": self.key, "total": self.total, "breached": self.breached,
                "breach_pct": round(self.breach_pct, 2)}


def _stats(key: str, rows: list[TicketSLA]) -> GroupStats:
    total = len(rows)
    breached = sum(1 for r in rows if r.is_breached)
    pct = (breached / total * 100.0) if total else 0.0
    return GroupStats(key=key, total=total, breached=breached, breach_pct=pct)


def summarize(results: list[TicketSLA]) -> dict:
    """Breach % per priority and per assignee group.

    Groups with no tickets are included with 0/0 → 0.0% only if they appear
    in the data; empty overall input yields empty groups, not an error.
    """
    by_priority: dict[str, list[TicketSLA]] = {}
    by_group: dict[str, list[TicketSLA]] = {}
    for r in results:
        by_priority.setdefault(r.priority, []).append(r)
        by_group.setdefault(r.assignee_group, []).append(r)

    return {
        "overall": _stats("ALL", results).as_dict(),
        "by_priority": {k: _stats(k, v).as_dict()
                        for k, v in sorted(by_priority.items())},
        "by_assignee_group": {k: _stats(k, v).as_dict()
                              for k, v in sorted(by_group.items())},
    }
