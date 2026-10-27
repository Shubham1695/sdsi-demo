# PS6 — IT Service-Desk SLA Tracker

Computes SLA breaches for support tickets: business-hours clock (Mon–Fri
09:00–18:00), holiday exclusions, and ON_HOLD pauses, with per-ticket results
and per-priority / per-group summaries.

Python 3.10+ · stdlib-only core · pytest for tests.

## Quick start

```bash
# from this directory
python -m sla_tracker \
  --tickets data/tickets.json \
  --policy  data/sla_policy.json \
  --holidays data/holidays.json \
  --now 2025-11-12T18:00:00 \
  --out results.json --csv results.csv --report summary.md
```

(`PYTHONPATH=src` may be needed depending on your environment; alternatively
`pip install -e .` — see below.) With no `--out/--csv/--report` the full
result JSON prints to stdout.

Run the tests:

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

## Input files

**tickets.json** — object with a `tickets` list (or a bare list):

```json
{
  "id": "TCK-1002",
  "priority": "P2",
  "assignee_group": "L2-Network",
  "created_at": "2025-11-03T11:00:00",
  "resolved_at": "2025-11-05T16:10:00",
  "status_history": [
    { "status": "OPEN", "at": "2025-11-03T11:00:00" },
    { "status": "ON_HOLD", "at": "2025-11-03T14:00:00" },
    { "status": "IN_PROGRESS", "at": "2025-11-04T09:30:00" },
    { "status": "RESOLVED", "at": "2025-11-05T16:10:00" }
  ]
}
```

**sla_policy.json** — targets (minutes) and the business calendar:

```json
{
  "business_hours": { "days": [1,2,3,4,5], "start": "09:00", "end": "18:00" },
  "targets_minutes": { "P1": 240, "P2": 480, "P3": 1440, "P4": 4320 }
}
```

**holidays.json** — `{"holidays": ["2025-12-25", ...]}` (ISO dates).

## Output

Per ticket (M4): `elapsed_business_minutes`, `due_by`, `is_breached`,
`breach_minutes`, plus `remaining_minutes`, `is_resolved`,
`currently_on_hold`. Summary (M5): breach % overall, per priority, per
assignee group. Writers: JSON, CSV, Markdown.

## Documented semantics (assumptions)

| Question | Decision |
|---|---|
| What does the SLA run to? | `resolved_at` if resolved; otherwise the `--now` cutoff. With no `--now`, the latest timestamp in the data is used so runs are deterministic. |
| Breach rule | Strictly greater: `elapsed == target` is **not** a breach. |
| Timestamps | ISO-8601, organization-local wall time. Offsets are accepted and normalised away (single-timezone operation is assumed). |
| Created outside business hours / on weekends / holidays | Clock effectively starts at the next business instant. |
| Resolved outside business hours | Elapsed counts to the close of the last business window. |
| ON_HOLD with no matching exit | Clock paused until the cutoff (or resolution). |
| Holds outside business hours | Pause only their in-window portion (usually zero). |
| Status vocabulary | `OPEN`, `IN_PROGRESS`, `ON_HOLD`, `RESOLVED`, `CLOSED`; anything else is a validation error. |
| Rounding | None internally; outputs are rounded to 2 decimals for display only. |

## Design notes

- **Closed-form calendar math, not minute-stepping.** `business_minutes_between`
  and `add_business_minutes` are O(#days), so a P4 ticket (72h = 8 business
  days) spanning weeks costs dozens of iterations, not hundreds of thousands.
  A minute-by-minute reference implementation lives in the tests and is used
  to cross-check the fast path.
- **One clock model.** Elapsed and due-by both go through the same calendar
  primitives; due-by is a fixpoint (holds before the deadline push it out).
- **Pure engine.** `calendar`/`engine`/`summary` have zero I/O — all I/O and
  validation live in `models`/`cli`/`report`. This makes the edge-case test
  matrix direct and deterministic.
- **Fail-fast validation.** Malformed JSON, unknown statuses, duplicate IDs,
  priorities without targets, inverted business hours — all rejected with
  precise messages and exit code 2, never silent wrong numbers.

## Testing

30 tests cover the edge-case matrix: boundary instants (09:00/18:00 exactly),
weekend/holiday creation and resolution, holds spanning weekends and
holidays, multiple/overlapping/duplicate holds, out-of-order history,
events predating creation, unresolved tickets, P4 multi-week spans,
round-trip `add` ↔ `measure` property checks, and input validation.

## Project layout

```
src/sla_tracker/
  models.py    # data models + eager input validation
  calendar.py  # business-hours primitives (closed-form)
  engine.py    # elapsed / due-by / breach (pure)
  summary.py   # breach % aggregations (M5)
  report.py    # JSON / CSV / Markdown writers
  cli.py       # argparse entry point
tests/         # edge-case matrix + round-trip property tests
data/          # sample inputs
```
