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

## Round 2 (S23): the imperative snippet (written 2026-11-20, before the run)

Round 1 (`empty` 2/30) leaves two candidate levers: the wording of the snippet and a Stop
hook. This round measures **only the wording**, with everything else frozen (scenario,
model, predicate, timeout).

New arm, `imperative`: the same empty `.cairn` as `empty`; the only difference is the
`AGENTS.md` text (`bench/ab.py:_snippet()`, the same block `setup.py` writes). The save rule
becomes an obligation with
a moment ("Before you reply, ask: did I learn a reason that lives only in this
conversation?") and says that the user's reason goes into `--why`. That is the failure this
scenario probes: the why exists only in the request.

Controls are reused, not re-run: `empty` 2/30 (IC95 0.018-0.213) and `plain` 0/30,
measured on 2026-11-20 with the same scenario and model.

1. **Primary:** `imperative`'s Wilson lower bound ≥ 0.5 (at least 21/30) and its interval
   does not overlap `empty`'s (LB > 0.213).
2. **No junk:** at least 20 of the winners must be about the timezone change, read by hand
   in the `--json` rows. The verdict is only published after reading them.
3. **Cost:** the token mean of the sessions must not exceed the round 1 `empty` mean
   (17,635 without the winners; 21,826 overall) by more than 25%.
4. **Harness health:** more than 10% of non-zero exits in the arm breaks the run, not the
   result.

If it fails, the wording lever is closed and the next round measures the Stop hook on its
own; the risk stays open.

**Outcome (2026-11-20):** 17/30 (IC95 0.392-0.726), 30/30 exits 0, 18,188 tokens. Criterion
1 fails (LB 0.392 < 0.5); the text is shipped anyway because it is 8.5x the control at -17 %
tokens (`docs/AB_RESULTS.md`). The next round is the Stop hook, with its own criteria.

### Harness defect found while round 2 ran (2026-11-20)

`bench/ab.py:_snippet()` cut the doc by line number, so the `empty` control's `AGENTS.md`
started with two prose lines of the doc and a stray ` ```markdown ` fence. Round 1's numbers
stand for that exact text: the defect adds noise to the control, it does not change its rule.
Fixed to extract the fenced block, and `tests/test_ab_write.py` now asserts the block equals
`cairn_mem.setup.SNIPPET`, so the measured text and the installed text cannot drift again.

## Round 3 (S27): the Stop hook (written 2026-11-21, before the run)

Round 2 closed the wording lever at 17/30. The remaining lever from the §6 risk row is a
hook that fires when the session goes idle. This round measures **only the hook**: the
scenario, the predicate and the model stay frozen.

### The arm

`stop`: the same empty `.cairn` and the same `AGENTS.md` as `imperative`, plus one
harness-side hook installed in the repo before the session. When a turn ends without a
cairn `save` in that session, the harness sends **one** short prompt asking for the reason
the user gave. The hook only asks: it never writes the memory itself, because the reason is
the model's to state, and an auto-save would measure a bypass instead of a behaviour.

- **One nudge per session, never more.** After the second silence the session ends. An
  unbounded hook would loop and burn tokens; that is a harness defect, not a result.
- **Not in any other arm.** `plain`, `empty` and `imperative` stay hookless: the delta is
  the hook and nothing else.
- **Its text is data for the run.** It lives in one directory the bench copies per run, and
  once `cairn setup` installs it, a test pins that copy to the installed text, the same way
  `tests/test_ab_write.py` pins `SNIPPET`. Measured text and shipped text cannot drift.
- **Not shipped by `setup` until the numbers exist.** The round measures first; a passing
  hook gets its own install path after the measurement.
- The hook is OpenCode's, because the bench runs `opencode run --auto`. Claude Code's `Stop`
  hook is a different mechanism and needs its own arm; nothing here is a claim about it.

### Criteria

n = 30 per arm, Wilson 95 %, `exit != 0` excluded and reported. Both arms run in **one
invocation, interleaved** (`--arms imperative,stop`), because the shipped snippet adds back
the `--personal` and `⚠ review` lines the round 2 candidate dropped and model drift would
otherwise favour one arm.

1. **Primary:** `stop`'s Wilson lower bound ≥ 0.5 (at least 21/30) on the unchanged
   predicate. Same bar as rounds 1 and 2, so the risk row can close on one number.
2. **Improvement over the wording alone:** `stop`'s lower bound exceeds `imperative`'s upper
   bound **in the same run**. If `imperative` reproduces 17/30 (UB 0.726), that is 27/30.
   Without this the hook is not better than the text it would ship with.
3. **No junk:** at least 20 of `stop`'s winners are about the timezone change, read by hand
   in the `--json` rows. The verdict is published only after reading them.
4. **Cost:** the token mean of `stop` must not exceed 1.75x `imperative`'s mean in the same
   run. One extra turn per session is expected; more means the agent is talking to itself.
5. **The hook fires:** every `stop` session that ends without a save has at least one nudge
   line in the hook's own log, and no session has more than one. If the hook does not fire,
   the arm is void, not a zero result.
6. **Harness health:** more than 10 % non-zero exits in either arm breaks the run.

### Decision rule

- 1 and 2 pass: ship the hook with the snippet, record the numbers in
  [`docs/AB_RESULTS.md`](../docs/AB_RESULTS.md), tick the §4.1 bullet and close the risk row.
- 1 passes, 2 fails: the hook helps but not measurably over the text; shipping it needs a
  row in [`docs/DECISIONS.md`](../docs/DECISIONS.md) saying so, and the risk row stays open.
- 1 fails: the hook lever is closed with its numbers, no install path is written, and the
  risk row stays open with the next candidate named.

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
python bench/ab_write.py --arms imperative,stop --reps 30 --json  # round 3
```

Results go to [`docs/AB_RESULTS.md`](../docs/AB_RESULTS.md).
