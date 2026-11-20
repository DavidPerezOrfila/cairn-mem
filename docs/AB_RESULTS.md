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
