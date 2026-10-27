# AI Collaboration Log (PROMPTS.md)

How AI (Claude Code) was used to build this submission, with the prompts that
shaped each phase and what changed as a result.

## Phase 1 — Problem analysis

> "I will give you a problem statement analyse it" (+ PS6 statement)

The analysis produced the milestone-to-complexity mapping and — most
valuably — the unlisted edge-case list (boundary instants, weekend/holiday
creation, holds spanning weekends, unresolved tickets, malformed input).
That list became the test matrix and the README assumptions table.

## Phase 2 — Technology decision

> "`<your-alias>` is my git username, and before building tell me what
> technology we will be using"

Decision made here: Python 3.10+ stdlib-only core + pytest. Rationale:
`datetime` covers all needs, the core is pure interval arithmetic (no
pandas/numpy warranted), pytest parametrization suits an edge-case matrix,
and zero install steps maximise the runnability score. Non-choices
(web framework, database, pandas) were recorded with reasons.

## Phase 3 — Build

> "yes start building"

Key AI-driven design corrections caught during the build (visible in the
git history as successive engine rewrites):

1. **Due-by shift bug.** The first due-by formula (`target + hold minutes`)
   wrongly shifted deadlines for holds occurring *after* the target was
   already consumed. Replaced with a fixpoint iteration where only holds
   falling before the current deadline push it out.
2. **Defensive sorting.** Direct `Ticket` construction (as in tests) bypassed
   the loader's history sort; the engine now sorts defensively itself.
3. **Inverted-range crash.** The fixpoint pass crashed via
   `business_minutes_between` on holds lying wholly after the deadline;
   fixed with an explicit overlap guard.

## Phase 4 — Test-fix loop

> (mid-build) "Commit my changes, push to my fork and open a pull request"

Initial run: 11 failed / 19 passed. Diagnosis: 9 failures were arithmetic
errors in the *test expectations themselves* (e.g. assuming Mon 09:00 + 480
min spills to Tuesday when it fits within Monday's 540-minute day; using the
P1 target in a P2 scenario), 2 were real code bugs (above). The loop of
hand-verify → fix → re-run converged to 30/30 green. This distinction —
test bugs vs code bugs — mattered; the AI traced each expectation by hand
against the calendar rather than "adjusting until green".

## What AI contributed

- Edge-case enumeration beyond the brief (explicitly weighted in judging).
- Closed-form vs minute-stepping performance design (judged criterion).
- Catching its own semantic bugs before commit via hand-verification of
  each sample-ticket result (TCK-1002 hold shift, TCK-1004 holiday span).
- Discipline around not committing red tests, even when asked mid-loop.
