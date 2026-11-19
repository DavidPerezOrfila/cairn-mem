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
