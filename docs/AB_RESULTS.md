# Paired A/B test (indicative)

Measured on **2026-11-02** with `python bench/ab.py --reps 2` (Windows 11, Python
3.14.10, OpenCode default model).

- 8 closed-answer tasks on a toy project. The answers are not in the code.
- 2 arms × 8 tasks × 2 repetitions = 32 runs, each in a clean copy of the project.
- The "with" arm had a seeded `.cairn` and an `AGENTS.md` built from
  `docs/AGENT_SNIPPET.md`.
- Human interventions: 0 (`--auto`).

| Arm | Success | Tokens (mean) | Tool calls (mean) |
|---|---|---|---|
| without memory | 0/16 | 26,826 | 6.3 |
| with memory | 16/16 | 20,982 | 7.6 |

With memory, the agent answers correctly every time. It makes more tool calls because it
searches and reads the memory, but it spends fewer tokens because it stops exploring the
code without a result. The arm without memory answers from what it can infer from the
code (for example, "read `RATE_LIMIT`") and fails.

With n=8 per arm, this is **indicative**. It shows that the memory gets used and saves
work. It does not show statistical significance. The protocol lives in
[`bench/ab_protocol.md`](../bench/ab_protocol.md).

# Write-side A/B (smoke, not the measurement)

**2026-11-19**, Windows 11, Python 3.12.10, OpenCode 2.3.2 default model,
`python bench/ab_write.py --arms plain,empty --reps 1`. The task changes `/health`'s
`time` field to epoch seconds because the data team consumes it from another timezone;
the reason exists only in the request. Success = a new `save` in `events.jsonl` that
mentions the topic (`epoch|utc|tz|timezone|iso|timestamp`).

| Arm | Saved | Tokens | Tool calls |
|---|---|---|---|
| `plain` (no snippet) | 0/1 | 20,710 | 6 |
| `empty` (snippet) | 0/1 | 8,618 | 6 |

Two earlier scenario versions were discarded before the measurement, with their numbers,
in [`bench/ab_write_protocol.md`](../bench/ab_write_protocol.md) (a one-line code bug: 0/5;
an environment gotcha the agent moved into `conftest.py`: 0/2). A separate probe confirmed
the model does receive the `AGENTS.md` snippet (it quoted the `cairn session save` line
verbatim), so these zeros are the model not saving, not a broken harness.

**This is a smoke, not the measurement**: n=1 per arm says nothing about the criterion
(n ≥ 30, Wilson 95%). It does show the harness runs end to end and that the risk "the
agent does not save memories" is still open for this model and scenario.

# Write-side A/B (measurement, 2026-11-20)

`python bench/ab_write.py --arms empty,plain --reps 30 --json` (Windows 11, Python
3.14.10, OpenCode 2.3.2 default model). Same scenario as the smoke. The criteria live in
[`bench/ab_write_protocol.md`](../bench/ab_write_protocol.md) and were written on
2026-11-19, before this run.

- 2 arms × 30 runs = 60 sessions, every one `exit == 0` (0 % harness failures).
- Success = a new `save` in `events.jsonl` whose title, body or why matches
  `epoch|utc|tz|timezone|iso|timestamp`.

| Arm | Saved | Wilson 95 % | Tokens (mean) | Tool calls (mean) |
|---|---|---|---|---|
| `plain` (no snippet) | 0/30 | 0.000-0.114 | 17,635 | 7.9 |
| `empty` (snippet) | 2/30 | 0.018-0.213 | 21,826 | 7.4 |

The two saves are the case the snippet asks for, not keyword noise: runs 1 and 20 record
that `health()` returns `int(time.time())` in epoch seconds **and** the reason (the data
team consumes the field from another timezone and cannot parse local ISO), anchored to
`app.py`. The other 28 runs wrote nothing at all: no `.cairn/events.jsonl`.

## Verdict against the criteria

1. **Primary, `empty`: FAILS.** Lower bound 0.018 against the required 0.5, and its
   interval overlaps `plain` (0.000-0.114). At n = 30 the snippet does not make this model
   save the decision it just took.
2. **`plain`: PASSES.** 0/30: without instructions the agent does not invent a store.
3. **Controls (`stale`, `poison`, `distractors`): NOT RUN.** They are scored relative to
   `empty` (a drop of at most 0.20), and at 2/30 that margin is indistinguishable from
   noise, so 90 more sessions would not answer anything. Those hypotheses stay untested
   and stay in the protocol.
4. **Harness health: PASSES.** 0 non-zero exits in 60 runs.

## What this means

Writing is the weak half of the product: retrieval is 16/16 (above), writing what was
learned is 2/30. "Save decisions with a reason" as prose is not enough. Candidate next
steps, none measured or implemented: a `Stop` hook that asks the session for the decisions
it took, and a shorter, imperative snippet. Until one is measured, the risk row "the agent
does not save memories" in `PLAN.md` §6 stays open.

# Write-side A/B, round 2: the imperative snippet (2026-11-20)

`python bench/ab_write.py --arms imperative --reps 30 --json` (Windows 11, Python 3.14.10,
OpenCode 2.3.2 default model). Same scenario, predicate and timeout as round 1; the only
change is the `AGENTS.md` text: the save rule becomes an obligation with a moment ("Before
you reply, ask: did I learn a reason that lives only in this conversation?") and says that
the user's reason goes into `--why`. Criteria for this arm were written before the run in
[`bench/ab_write_protocol.md`](../bench/ab_write_protocol.md).

| Arm | Saved | Wilson 95 % | Tokens (mean) | Tool calls (mean) |
|---|---|---|---|---|
| `empty` (round 1 snippet, reused) | 2/30 | 0.018-0.213 | 21,826 | 7.4 |
| `imperative` | 17/30 | 0.392-0.726 | 18,188 | 8.5 |

The control is round 1's, not re-run: same scenario, model and machine, the same day.

## Verdict against the criteria

1. **Primary: FAILS.** 17/30 gives a Wilson lower bound of 0.392 against the required 0.5.
   The interval does not overlap the control's (0.392 > 0.213) and the point estimate is
   8.5x the control's, but the pre-registered bar was "the snippet makes the agent save",
   and 57 % is not that. The goal was not moved after seeing the number.
2. **No junk: NOT VERIFIABLE after the fact.** Round 2's rows carry the saved ids but not
   their text, and the bench deletes the temp repo. The harness now puts `kind`, `title`,
   `body` and `why` of every counted save in the row (`saves`), so the next round can be
   read. A harness gap, recorded, not a result.
3. **Cost: PASSES.** 18,188 tokens against the control's 21,826 (-17 %): the obligation
   does not cost more tokens.
4. **Harness health: PASSES.** 30/30 runs `exit == 0`.

## What this means

Wording moved the rate from 2/30 to 17/30 at a lower token cost, so the imperative text is
shipped as the snippet (`cairn_mem.setup.SNIPPET` and `docs/AGENT_SNIPPET.md`, pinned equal
by a test) even though it fails the bar: it is better on every measured axis and nothing
else changed. The shipped text adds back the `--personal` and "⚠ review" lines the
candidate dropped; round 3 re-measures it as its control.

The risk "the agent does not save memories" stays open at 57 %. The next lever is a `Stop`
hook that asks for the decisions when the session goes idle; it gets its own round and its
own criteria, written before it runs.

Two harness defects found while running round 2, both fixed: `bench/ab.py:_snippet()`
sliced the doc by line number, so round 1's control carried two prose lines and a stray
fence in `AGENTS.md` (those numbers stand for that text; a test now pins the block to
`cairn_mem.setup.SNIPPET`), and the rows lost the saved text (above).

# Write-side A/B, round 3: the Stop hook (2026-11-21)

`python bench/ab_write.py --arms imperative,stop --reps 30 --json` (Windows 11, Python
3.14.10, OpenCode 2.3.2, deepseek-v4.1-flash). Both arms in **one invocation,
interleaved**, because the shipped snippet is not the round 2 candidate. Criteria written
before the run in [`bench/ab_write_protocol.md`](../bench/ab_write_protocol.md)
§"Round 3 (S27)".

The arm: the same `AGENTS.md` and empty `.cairn` as `imperative`, plus a local OpenCode
plugin (`bench/assets/stop/index.ts`) that waits for `session.execution.succeeded`, counts
`save` events in `.cairn/events.jsonl`, and when the count did not move sends **one**
prompt asking for the reason. It never writes the memory itself and only acts on sessions
whose `location.directory` is its own project.

| Arm | Saved | Wilson 95 % | Tokens (mean) | Tool calls | Sessions nudged |
|---|---|---|---|---|---|
| `imperative` (snippet only) | 20/30 | 0.488-0.808 | 14,673 | 8.9 | 0 |
| `stop` (snippet + hook) | 30/30 | 0.886-1.000 | 16,329 | 10.0 | 7 |

## Verdict against the criteria

1. **Primary: PASSES.** 30/30, Wilson lower bound 0.886 against the required 0.5; ten
   sessions more than the text alone in the same run.
2. **Improvement over the wording alone: PASSES.** Lower bound 0.886 exceeds `imperative`'s
   upper bound 0.808 for that run.
3. **No junk: PASSES.** All 30 winners record the timezone reason (titles and `why` read in
   the `--json` rows), not keyword noise.
4. **Cost: PASSES.** 1.11x the text-only arm (16,329 against 14,673 tokens), well inside the
   1.75x bound: the extra turn is paid only when the first turn wrote nothing.
5. **The hook fires: PASSES.** Seven sessions ended their first turn without a save; each
   got exactly one nudge and each saved in the nudge turn. Zero sessions ended unsaved and
   zero got more than one nudge. `imperative` shows zero nudges, so the delta is the hook.
6. **Harness health: PASSES.** 60/60 runs `exit == 0`.

`imperative` scored 20/30 here against 17/30 in round 2: the shipped text adds the
`--personal` and "⚠ review" lines the candidate dropped, and the model drifts. That is
why the paired comparison, not round 2's number, is the criterion.

## A harness finding worth keeping

The plugin API is server-wide: a plugin subscribed to `session.execution.succeeded` receives
events from **every** session on the shared service, and a first version of the probe nudged
sessions in other projects until its instance was unloaded. The shipped hook filters by
`session.location.directory` (and skips `parentID`), and that filter was verified: a session
in another directory gets no nudge. Any future cairn hook needs the same guard.

## What this means

The hook closes the gap the text could not: 100 % against 67 % with the same instructions and
the same model, for 11 % more tokens. The risk row "the agent does not save memories" is
closed by measurement. The install path (`cairn setup` writing the hook per harness) is the
next round; nothing is shipped by `setup` yet.

## Install-path smoke (S28, 2026-11-22)

`python bench/ab_write.py --arms imperative,stop --reps 10 --json` with the hook installed by
`cairn setup opencode` (the bench now calls `setup.install_hook`, not a copy of the asset),
same machine and model as round 3.

| Arm | Saved | Exits 0 | Nudges |
| --- | ----- | ------- | ------ |
| `imperative` | 7/10 | 10/10 | 0 |
| `stop` (installed hook) | 8/10 | 10/10 | 2 |

The smoke checks the install path, not the rate: the plugin loads from
`.opencode/plugins/cairn-stop/`, fires once per session (2 sessions), and every run exits 0.
At n = 10 the difference is inside the noise; round 3's 30/30 remains the measurement.

# Write-side A/B, round 4: the Claude Code Stop hook (2026-11-24)

Measured on Windows 11 with Claude Code headless:

```console
python bench/ab_write.py --harness claude-code --arms empty,stop --reps 30 --json --rows-file bench/cc-round4-rows.jsonl
```

Both arms ran in one invocation, interleaved. The scenario, predicate and shipped snippet
stayed frozen; only the project `Stop` hook changed. Criteria were written before the run in
[`bench/ab_write_protocol.md`](../bench/ab_write_protocol.md) §"Round 4".

| Arm | Saved | Wilson 95 % | Tokens (mean) | Turns (mean) | Sessions nudged |
|---|---|---|---|---|---|
| `empty` (snippet only) | 16/30 | 0.361-0.698 | 295,983 | 10.2 | 0 |
| `stop` (snippet + hook) | 30/30 | 0.886-1.000 | 338,604 | 11.5 | 17 |

The run completed all 60 sessions before the 70-minute session limit, with 60/60
`exit == 0`. Raw evidence: [`bench/cc-round4-rows.jsonl`](../bench/cc-round4-rows.jsonl).

## Verdict against the criteria

1. **Primary: PASSES.** 30/30, Wilson lower bound 0.886 against the required 0.5.
2. **Improvement over the wording alone: PASSES.** 0.886 exceeds `empty`'s upper bound
   0.698 in the same interleaved run.
3. **No junk: PASSES.** The 30 winning rows were read by hand; every one records the
   timezone/epoch change and why the data team cannot parse local ISO.
4. **Cost: PASSES.** 338,604 against 295,983 mean tokens: 1.144x, below the 1.75x bound.
5. **The hook fires: PASSES.** 17 sessions were nudged exactly once and all 17 saved;
   no session was nudged more than once.
6. **Harness health: PASSES.** 60/60 runs `exit == 0`.

## What this means

Claude Code's `Stop` hook closes the same gap as OpenCode's: the snippet alone saved 16/30,
while one nudge at session end raised it to 30/30 for 14.4 % more tokens. The decision rule
therefore calls for shipping the hook through `setup claude-code`. The install path and its
tests are the next slice; this measurement does not claim that path is finished.

# MCP tool-selection eval: baseline vs `v1` (2026-11-23)

`python bench/eval_mcp_tools.py --arm <name> --reps 1` over the same 20 seeded cases
(opencode default model, Windows 11). Grading is programmatic over the trace: expected tool
plus required args, forbidden tools, and final-answer `contains` for the read cases.
Baseline arm = one-sentence tool descriptions; `v1` = the full tool-and-parameter contract
(the audit Group 3 fix in `mcp.py`).

| Arm | Pass | Wilson 95 % | Tokens |
| --- | ---- | ----------- | ------ |
| baseline | 17/20 (85 %) | 0.64-0.95 | 263,539 |
| `v1` (full contract) | 16/20 (80 %) | 0.58-0.92 | 513,833 |

The intervals overlap: at n = 20 the eval cannot distinguish the arms. **Decision: the
description diff stays** — it is an audit completeness fix (parameter descriptions), not a
score optimization, and the eval remains the regression harness for it.

Per-case failures:

- baseline: `c04` (saved nothing), `c17` (missed `stale=true`), `c18` (called `get` with a
  non-12-hex id).
- `v1`: `c03` (no cairn call), `c05` (claimed `save_session` without calling it), `c17`
  (searched without the `kind` filter), `c18` (same as baseline).

## Harness findings: the eval agent is not sandboxed (2026-11-23)

The negative cases passed the grade while their agents reached outside the temp project
through `shell`:

- `c09` ("fix the config-parser bug", expected: no cairn tools) found a **real** bug in the
  installed `cairn` 0.17.0, fixed it in this repo and left branch `fix/config-bom` with
  commit `5803958` (`setup.py` reads the harness config with `utf-8-sig`, plus a passing
  test). The fix is genuine — `main` lacks it (the audit's BOM fix was `store.py`'s JSONL
  decode, a different file) — and is kept as a branch for a PR.
- `c13` ("archive what you no longer use") archived **29 real dogfood memories** of this
  repo's `.cairn/`.
- `c14` ("delete the project memory") deleted this repo's real `events.jsonl` (146 events),
  leaving its own backup in `%TEMP%\cairn-backup\`.

Repaired the same day: the log restored from `c14`'s backup, the 29 archive events stripped
(safety copy `events-pre-repair.jsonl` beside it; 115 saves + the 2 historical archives
remain, `doctor` clean apart from the two known `secrets` fails). Two grade gaps stay open:
the grader counts cairn tool calls but not `shell` side effects, and `CAIRN_DIR` pins the
CLI but not the agent. The negative cases need containment (or side-effect grading) before
the next full run.
