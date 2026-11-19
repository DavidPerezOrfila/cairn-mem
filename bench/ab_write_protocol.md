# Write-side A/B (S21): does the agent save the gotcha it just hit?

The first A/B (`bench/ab.py`) measured **retrieval**: does memory answer a question the
code cannot. It never measured usefulness in the other direction: after a session where
the agent discovers something, does it write it down? `bench/ab_write.py` measures that.

## Design

One session per run, `opencode run --auto`, clean copy of a toy repo per run:

- `app.py` returns `{"status": "ok", "time": <ISO local>}` from `/health`; `test_app.py`
  expects `int` (epoch seconds) and fails. The task says **why**: the data team consumes
  the field from another timezone and cannot parse local ISO. The agent changes one line;
  the *reason* only exists in the conversation, so it is the "decision with a reason" the
  snippet asks the agent to save, and it is not recoverable from the repo afterwards.
- After the session, the run counts as a success when `.cairn/events.jsonl` gained at
  least one `save` **whose id did not exist before the run** and whose title, body or why
  matches `\b(epoch|utc|tz|timezone|iso|timestamp)\b`. A run that saves something else
  does not count; neither does a pin (same id) or a seeded memory.
- Arms (seeded before the session):
  - `plain`: no `.cairn`, no `AGENTS.md`. Control: there is nowhere to write.
  - `empty`: `.cairn` plus the standard snippet in `AGENTS.md`. The normal install.
  - `stale`: like `empty` plus one memory anchored to `app.py` that says the field is ISO
    local, and `app.py` edited after seeding, so the entry renders `⚠ review`.
  - `poison`: like `empty` plus a wrong memory ("the data team requires local ISO") that
    the request contradicts.
  - `distractors`: like `empty` plus 100 filler memories.

### Scenarios rejected before the measurement (2026-11-19)

1. **v1, a real code bug** (naive `datetime.now()`): 0/5 in the smoke. The gotcha became
   readable from the code after one line, and the snippet says "do NOT save anything you
   can work out from the code". The arm was measuring a case the product excludes.
2. **v2, an environment gotcha** (`TZ=Europe/Madrid` needs exporting): 0/2 in the smoke.
   Both agents fixed it inside the repo (`conftest.py` sets `TZ`), so the gotcha turned
   into code again.
3. **v3, current**: a decision whose reason exists only in the user's request.

The criteria below did not change across these revisions.

## Criteria (written 2026-11-19, before the first run)

n ≥ 30 per arm, Wilson 95% interval, runs with `exit != 0` excluded and reported.

1. **Primary, `empty`:** the saved rate's Wilson lower bound is ≥ 0.5 **and** its interval
   does not overlap the `plain` interval. Otherwise the snippet does not make the agent
   save, and the risk row "The agent does not save memories" stays open.
2. **`plain`:** ≤ 0.10. A higher rate means the agent invents a store by itself and the
   control is not a control.
3. **Controls (`stale`, `poison`, `distractors`):** each saved rate may fall at most 0.20
   below `empty`'s. A larger drop means stale flags, a wrong memory or index size stop the
   agent from writing, and that is a bug to fix, not a result.
4. **Harness health:** if more than 10% of the runs in any arm exit non-zero, the scenario
   is broken; fix the bench before reading the numbers.

## Limits

- One model, one scenario, one language: it measures what the snippet achieves with that
  setup, not a claim about "agents in general".
- The keyword predicate is coarse: a save that mentions "timestamp" for an unrelated
  reason counts. Inspect the `--json` rows before publishing a number.
- An agent may write the reason into a `README` or a code comment instead of the memory.
  That is a real alternative behavior and counts as a failure here: the snippet tells it
  where that knowledge goes.
- `plain` can still find `cairn` on `PATH`; it is a control for "no instructions", not for
  "no binary".

## Run it

```bash
python bench/ab_write.py --arms plain,empty --reps 1     # smoke: 2 sessions
python bench/ab_write.py --reps 30                       # the measurement in the criteria
python bench/ab_write.py --reps 30 --json                # full rows
```

Results go to [`docs/AB_RESULTS.md`](../docs/AB_RESULTS.md).
