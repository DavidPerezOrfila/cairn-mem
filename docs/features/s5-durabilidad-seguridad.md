# S5: durability and security of the source of truth

**Goal:** close the three P0 findings reproduced in the 2026-11-06 audit before touching
ranking or features. A `save` must not corrupt `events.jsonl`, lose external events or
accept credentials.

## Scope

- Torn tail: a crash in the middle of an `os.write` leaves a line without `\n`. Before
  appending, `append_jsonl` repairs the tail. If the fragment is valid JSON, it adds the
  `\n`. If it is not, it truncates it. Without this, the next `save` appended its event to
  the fragment and the `rebuild` failed with `JSONDecodeError` on an intermediate line.
  This covers `events.jsonl` and `sessions.jsonl`, which share `append_jsonl`.
- External replacement with the same size: `Store._append` compares the full
  `(size, mtime_ns)` fingerprint from before the append, not just the size. A
  `git checkout` or `cp` that changes the content without changing the size no longer
  certifies a false fingerprint. It triggers a `rebuild` and indexes the remote events.
- Prefixed tokens: cairn now rejects `ghp_`, `github_pat_`, `glpat-`, `sk-proj-`,
  `sk-ant-`, `AIza` and other credential prefixes. Before, it only caught `key = value`.
- Validated `id` and `topic_key`: `id` must be 12 lowercase hex characters. `topic_key`
  cannot contain control characters and is limited to 100 characters. A 4,000-character
  topic left the L0 with just the title, and a newline injected fake lines into
  `MEMORY.md`. `render._line` also collapses the topic when reading, for files already
  contaminated by external events.
- The importer validates the topic in `--dry-run` just like a real import.

Out of scope: incremental sync (S7), the JSONL format, ranking.

## Acceptance criteria

1. A `save` after a torn tail leaves the JSONL valid line by line and does not lose the
   previous memory.
2. An external replacement with the same size and a different mtime is detected on the
   next `save`, and the remote memory gets indexed.
3. The listed token prefixes are rejected and never written.
4. A non-hex `id`, a `topic_key` with a newline, or a topic over 100 characters returns a
   `ValueError` and writes nothing. The L0 accepts no injected lines.
5. Suite and `ruff` pass.

## Evidence (2026-11-07)

- `pytest -q`: **175 passed** (22 new: 18 in `tests/test_store.py`, 1 in
  `tests/test_sessions.py`, 3 in `tests/test_jsonl.py`). Before: 153.
- `ruff check src tests bench`: clean.
- The tests pin the defect: with a size-only comparison (the old code), the same-size
  replacement test fails (`assert [] == ['remot']`). With the full fingerprint, it passes.
  The tail repair is tested in its three branches: a valid fragment without `\n` is kept,
  valid JSON that is not an object is truncated, and a fragment over 64 KiB is truncated.
- P0 reproduced before the change: (1) `events.jsonl` plus `{"op":"save","id":"` with no
  newline made the next `save` raise `JSONDecodeError` on rebuild; (2) a same-size
  replacement with a different mtime left `search("remot")` empty; (3) `ghp_`/`sk-`/`AIza`
  tokens were accepted; (4) a `topic` with `\n` injected a line into the L0, and a
  4,000-character topic left the L0 with just the title.
- `python bench/bench_mcp.py --reps 20` (10k): search 8.9 / save 18.6 / context 14.3 ms
  p95, so the **SLO < 50 ms passes**.
- `python bench/bench_cli.py --reps 20`, paired against v0.6.0 on the same machine:
  v0.6.0 1k search p95 328.4 / save 354.8 and 10k search p95 406.4 / save 389.4; the
  branch 1k 368.9 / 342.9 and 10k 325.4 / 349.6; internal search 3.7 → 3.6 ms. Machine
  noise (±40 ms) is larger than the difference, so there is **no regression**.
- Read-only review of the diff (subagent): it found that the replacement test used
  `write_text`, which on Windows adds `\r\n` and changed the size, so the test also passed
  with the old code. Fixed with `write_bytes` and verified red against the previous
  comparison. Tests for the `_repair_tail` branches were added.
- **0.7.0 release:** published on PyPI on 2026-11-07 (wheel and sdist).
  `pip index versions cairn-mem` returns 0.7.0. A clean install in a venv from PyPI was
  verified with `init`, `save`, `search`, `session save` and `session list`. On that
  wheel, a `ghp_` token is rejected (exit 1), and a `save` after a torn tail works and is
  found again with `search`. The first `uv publish` uploaded 0.6.0 because `dist/` had not
  been rebuilt. We deleted `dist/` and `build/` and built again (a lesson from
  AGENTS.md).
