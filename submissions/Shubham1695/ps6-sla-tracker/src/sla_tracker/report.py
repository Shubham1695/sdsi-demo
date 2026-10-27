"""Output writers: JSON (canonical), CSV, and a Markdown summary table."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .engine import TicketSLA
from .summary import summarize

_TICKET_COLUMNS = ["ticket_id", "priority", "assignee_group", "target_minutes",
                   "elapsed_business_minutes", "due_by", "is_breached",
                   "breach_minutes", "is_resolved", "currently_on_hold",
                   "remaining_minutes"]


def results_to_dict(results: list[TicketSLA], summary: dict) -> dict:
    return {
        "tickets": [
            {
                "ticket_id": r.ticket_id,
                "priority": r.priority,
                "assignee_group": r.assignee_group,
                "target_minutes": r.target_minutes,
                "elapsed_business_minutes": round(r.elapsed_business_minutes, 2),
                "due_by": r.due_by.isoformat(timespec="seconds"),
                "is_breached": r.is_breached,
                "breach_minutes": round(r.breach_minutes, 2),
                "is_resolved": r.is_resolved,
                "currently_on_hold": r.currently_on_hold,
                "remaining_minutes": round(r.remaining_minutes, 2),
            }
            for r in results
        ],
        "summary": summary,
    }


def write_json(results: list[TicketSLA], summary: dict, path: Path) -> None:
    payload = results_to_dict(results, summary)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_csv(results: list[TicketSLA], path: Path) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_TICKET_COLUMNS)
    for r in results:
        writer.writerow([
            r.ticket_id, r.priority, r.assignee_group, r.target_minutes,
            round(r.elapsed_business_minutes, 2), r.due_by.isoformat(timespec="seconds"),
            r.is_breached, round(r.breach_minutes, 2), r.is_resolved,
            r.currently_on_hold, round(r.remaining_minutes, 2),
        ])
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")


def summary_markdown(summary: dict) -> str:
    """Human-readable summary tables (overall + per priority + per group)."""
    def table(title: str, rows: list[dict]) -> str:
        lines = [f"### {title}", "", "| Group | Tickets | Breached | Breach % |",
                 "|---|---:|---:|---:|"]
        lines += [f"| {r['key']} | {r['total']} | {r['breached']} | {r['breach_pct']}% |"
                  for r in rows]
        lines.append("")
        return "\n".join(lines)

    parts = ["## SLA Summary", ""]
    parts.append(table("Overall", [summary["overall"]]))
    parts.append(table("By priority", list(summary["by_priority"].values())))
    parts.append(table("By assignee group", list(summary["by_assignee_group"].values())))
    return "\n".join(parts)
