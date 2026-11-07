# S2: `topic_key` is visible and searchable

**Goal:** the stable key of a memory (`topic_key`) should show up in the L0 and in
`search`, and FTS5 should index it together with the anchor path. That way the agent can
ask for "the `storage/fts5` thing" or "the `src/auth.py` thing" without remembering the
title.

## Scope

- FTS5 starts indexing `topic_key` and `anchor_path` in addition to `title`, `body` and
  `why`. BM25 weights: title 5, topic 3, anchor 2, body 1, why 0.5.
- `search` returns `topic_key` in JSON and shows it in text when present.
- The L0 shows `[topic]` between the `kind` and the title, only when the memory has a
  topic.
- `SCHEMA_VERSION` goes from 2 to 3. When an old database opens, the derived schema is
  dropped and rebuilt from `events.jsonl`. There is no manual migration and no new event.

Out of scope: L0 quotas, a new ranking, `hits`, changes to `archive` or the MCP tools.

## Acceptance criteria

1. `search "storage/fts5"` and `search "src/auth"` find the memory by topic and anchor.
2. `search --json` includes `topic_key`, and text output shows it without breaking the
   current format.
3. The L0 includes `[topic]` when it exists, stays ≤ 3,000 characters and stays
   deterministic.
4. A database with `user_version = 2` rebuilds itself on open and becomes searchable by
   topic.
5. Precision@3 stays at 30/30. Suite and `ruff` pass. MCP `search` p95 < 50 ms with 10k.

## Evidence (2026-11-04)

- `pytest -q`: **138 passed** (10 new tests: store, render, CLI and MCP).
- `ruff check src tests bench`: clean.
- macOS CI 3.14 caught a race: with `user_version=0`, dropping the schema removed tables
  another `Store` was using (`no such table: mem`). The drop now only acts on schemas 1
  and 2. There is a regression test, and 5 consecutive runs of the concurrency test
  passed.
- Precision@3: 30/30 (`pytest -q tests/test_golden.py`).
- Real migration: the repository store went from `user_version=2` to 3 on open, without
  touching the JSONL. `cairn search "release/0.3.1"` returns the memory by topic.
- `python bench/bench_cli.py --reps 20` (10k): search p95 150.6 ms, save p95 137.8 ms,
  internal 2.2 ms. `bench_mcp`: search 2.3 / save 9.4 / context 5.8 ms p95.
- Repository L0: 2,927 characters, 14 lines, `[topic]` visible on all of them.
- Topic baseline: 39 active memories, 39 with `topic_key`, 4 repeated keys when superseded
  entries are included (5 superseded). There are no active duplicates (partial unique
  index).
