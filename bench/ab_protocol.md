# Small paired A/B test (indicative)

Goal: does project memory reduce effort (tokens, tool calls) and improve success on tasks
that depend on knowledge you cannot infer from the code?

Design (`bench/ab.py`):

- 8 closed-answer tasks on a toy project whose answers are **not** in the code.
- Two arms, same model and same prompt:
  - without: clean project, no `.cairn` and no `AGENTS.md`.
  - with: `.cairn` seeded with the 8 facts, plus the snippet from
    `docs/AGENT_SNIPPET.md` in `AGENTS.md`.
- 2 repetitions per task and arm (32 runs). Each run uses a clean copy of the project.
- Metrics: success (the answer contains the expected fact), input and output tokens, and
  tool calls.
- Human interventions: 0 (it runs with `--auto`).

With n=8 per arm, the result is **indicative**, not conclusive. It measures whether the
memory gets used and saves work. It does not measure statistical significance.

Run it:

```bash
python bench/ab.py --reps 2          # summary table
python bench/ab.py --reps 2 --json   # full rows
```
