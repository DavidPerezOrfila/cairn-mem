# Measurement (M4)

- `bench_cli.py`: **end-to-end** time (Python startup included) for `cairn search` and
  `cairn save`, p50/p95, with 1k and 10k synthetic records. Run it on the real machine
  (Windows): `python bench/bench_cli.py --reps 20 [--json]`. Results are in
  [`docs/BENCHMARKS.md`](../docs/BENCHMARKS.md).
- `golden.jsonl`: 20 seeded memories and about 30 `{query, expected title}` queries,
  used to measure precision@3 without an LLM (`tests/test_golden.py`).
- `retrieval.jsonl` and `bench_retrieval.py`: S6 honest benchmark (52 memories, 37
  lexical/paraphrase/multi/no-answer queries, Hit@3, Recall@5, MRR and abstention
  against a grep baseline). `--distractors N` adds deterministic filler to measure the
  ranking as the index grows. Run `python bench/bench_retrieval.py [--json]
  [--distractors N]`. Results are in [`docs/BENCHMARKS.md`](../docs/BENCHMARKS.md).
- `bench_anchors.py`: marginal cost of anchors in `save` (10k memories, newest anchored),
  the measurement behind the `anchor_cache` decision. Run
  `python bench/bench_anchors.py --reps 30 [--json]`.
- `bench_sync.py`: S7 incremental sync latency with two writers over 10k (save and search
  after the other writer appended). Run `python bench/bench_sync.py --reps 40 [--json]`.
  Results are in [`docs/BENCHMARKS.md`](../docs/BENCHMARKS.md).
- `ab_protocol.md`: the small paired A/B test (see PLAN.md). `ab.py` runs it with
  OpenCode. Results are in [`docs/AB_RESULTS.md`](../docs/AB_RESULTS.md).

Every bench measures inside a `TemporaryDirectory` and closes its `Store` on every path
(`closing`), so no directory is left behind (`Windows` keeps an open SQLite file
undeletable). `bench_cli.py`, `bench_mcp.py` and `bench_sync.py` exit with 1 when an SLO
fails, with and without `--json`, so a release script can just check the exit code.
