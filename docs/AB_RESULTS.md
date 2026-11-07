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
