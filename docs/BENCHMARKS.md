# Benchmarks (M4)

Measured on **2026-11-02** on the real machine.

- Windows 11 Pro 10.0.26300, 16 GB RAM, Python 3.14.10.
- Command: `python bench/bench_cli.py --reps 20` (seed through JSONL plus rebuild; the
  CLI is measured with `python -m cairn_mem.cli`, Python startup included).

## End-to-end latency

| Records | Load | rebuild | search p50 | search p95 | save p50 | save p95 | internal search p95 |
|---|---|---|---|---|---|---|---|
| 1,000 | 54 % | 212 ms | 353 ms | 378 ms | 387 ms | 398 ms | 1.1 ms |
| 10,000 | 54 % | 1,816 ms | 361 ms | 390 ms | 534 ms | 636 ms | 4.8 ms |
| 1,000 | 16 % | 172 ms | 292 ms | 317 ms | 318 ms | 331 ms | 0.8 ms |
| 10,000 | 16 % | 1,303 ms | 283 ms | 304 ms | 439 ms | 451 ms | 5.9 ms |

The first pass ran with the editor and agent using the CPU. The second pass ran with the
machine idle (16 %).

## MCP (in-process tool call, 10k records)

`python bench/bench_mcp.py --reps 20` (2026-11-02, same machine):

| Tool | p50 | p95 |
|---|---|---|
| `search` | 3.4 ms | 4.0 ms |
| `save` | 28.4 ms | 37.4 ms |
| `context` (L0) | 14.5 ms | 18.4 ms |

The new SLO is a tool call p95 < 50 ms. It **passes**, with no Python startup.

## Precision@3

`python -m pytest tests/test_golden.py` gives **30/30 = 1.00**. The golden set has 20
memories and 30 queries, with no LLM involved.

## Startup floor

Measured on an idle machine (10 runs, p50):

| Process | p50 |
|---|---|
| `python -c pass` | 72 ms |
| `import sqlite3, json, re` | 138 ms |
| `import sqlite3, json, re, secrets, hashlib, pathlib` | 169 ms |
| `import cairn_mem.cli` | 178 ms |

The original SLO (`search` < 150 ms) is below the cost of importing the standard library
you need before touching the database. You cannot reach it without changing the
architecture (a daemon or a native binary). That measurement is why §2 of PLAN.md now
sets `search` p95 < 350 ms and `save` p95 < 500 ms on an idle machine with 10k records.

## Verdict against §2 of PLAN.md (revised)

- Internal `search`: **passes** (< 10 ms).
- Precision@3: **passes** (≥ 0.8).
- End-to-end `search` on an idle machine: **passes** (304 ms < 350 ms). `save`:
  **passes** (451 ms < 500 ms).
- 10k rebuild: 1.3 s (PLAN.md asked us to measure it, with no target).

## Decision

We did not touch the L0, the ranking or the save rules. The internal query and precision
pass, and the remaining margin sits in process startup, not in the memory design.
Optimizing startup (a custom parser, lazy imports) stays in the backlog, and only if the
A/B test or real usage shows it hurts.

L0 with 1k memories: 2,944 characters (≤ 3,000) and byte-identical when reopened (see
`PLAN.md`, M2).

## L0 round-robin (S1, 2026-11-04)

`python bench/bench_mcp.py --reps 20` with 10k records, same machine:

| Tool | p50 | p95 |
|---|---|---|
| `search` | 6.7 ms | 10.6 ms |
| `save` | 24.2 ms | 27.6 ms |
| `context` (L0) | 18.0 ms | 23.0 ms |

- `active_ordered` with 10k: 8.2 ms p50 (13.3 ms p50 before).
- `cairn render` end-to-end: 288-393 ms (315-376 ms earlier that day).
- Repository L0: 2,919 characters and 15 `decision` lines became 2,991 characters with
  5 `decision`, 5 `gotcha` and 5 `fact`.
- Details and criteria: [`docs/features/l0-fair-share.md`](features/l0-fair-share.md).

## S2: topic and anchor in FTS (2026-11-04)

`SCHEMA_VERSION=3`: `mem_fts` indexes `title, body, why, topic_key, anchor_path` with
weights `5.0, 1.0, 0.5, 3.0, 2.0`. Measured on the same machine on an idle system (the M4
pass ran with the agent using the CPU, which explains the difference):

`python bench/bench_cli.py --reps 20`:

| Records | rebuild | search p95 | save p95 | internal search p95 |
|---|---|---|---|---|
| 1,000 | 92 ms | 156.4 ms | 147.2 ms | 0.3 ms |
| 10,000 | 570 ms | 150.6 ms | 137.8 ms | 2.2 ms |

`python bench/bench_mcp.py --reps 20` with 10k:

| Tool | p50 | p95 |
|---|---|---|
| `search` | 1.8 ms | 2.3 ms |
| `save` | 8.1 ms | 9.4 ms |
| `context` (L0) | 4.6 ms | 5.8 ms |

- Precision@3: 30/30 (`pytest -q tests/test_golden.py`).
- Repository L0: 2,927 characters, 14 lines, all with `[topic]`.
- Topic baseline on the real store: 39 active memories, 39 with `topic_key`, 4 repeated
  keys when superseded entries are counted (5 superseded).
- Details and criteria: [`docs/features/topic-visibility.md`](features/topic-visibility.md).

## S3: cross-scope search and project session (2026-11-04)

`cairn search` queries the project and the personal scope, then interleaves results by
ranking position. `context` only injects project sessions. Measured on the same machine
with the real personal scope (18 memories) and the agent loading the CPU, so the absolute
numbers are not comparable with the idle S2 pass:

`python bench/bench_cli.py --reps 40`:

| Records | rebuild | search p95 | save p95 | internal search p95 |
|---|---|---|---|---|
| 1,000 | 219 ms | 336.9 ms | 391.4 ms | 3.0 ms |
| 10,000 | 2,989 ms | 309.3 ms | 329.6 ms | 4.5 ms |

`python bench/bench_mcp.py --reps 40` with 10k and the real personal scope:

| Tool | p50 | p95 |
|---|---|---|
| `search` | 4.3 ms | 6.6 ms |
| `save` | 15.3 ms | 17.9 ms |
| `context` (L0 + project session) | 9.0 ms | 12.4 ms |

- Cost of the second database: with 20 repetitions, MCP `search` p95 was 7.4 ms with the
  real personal scope and 4.7 ms without `~/.cairn`. The internal query does not change.
- A later `bench_mcp` run with the agent loading the CPU gave search 13.5 / save 29.9 /
  context 31.0 ms p95. The 50 ms SLO still holds.
- With 20 repetitions on that busy machine, an end-to-end `search` p95 of 624-683 ms
  appeared because of a slow process startup (p50 stayed around 300 ms). With 40
  repetitions, both sizes pass.
- Precision@3: 30/30. Details and criteria:
  [`docs/features/transversal-search.md`](features/transversal-search.md).

## S6: retrieval quality (2026-11-08)

Baseline measured **before** the S6.1 query-side fix, kept for comparison.

The legacy precision@3 uses queries built from title words: 30/30 only proves the search
works. `python bench/bench_retrieval.py` measures against a corpus with confusables and a
grep baseline (52 memories, 37 queries, no LLM):

| Category | n | System | Hit@3 | R@5 | MRR |
|---|---|---|---|---|---|
| lexical | 12 | cairn | 1.00 | 1.00 | 1.00 |
| lexical | 12 | grep | 1.00 | 1.00 | 1.00 |
| paraphrase | 10 | cairn | 0.90 | 0.90 | 0.80 |
| paraphrase | 10 | grep | 0.90 | 0.90 | 0.85 |
| multi | 7 | cairn | 1.00 | 0.95 | 1.00 |
| multi | 7 | grep | 1.00 | 0.95 | 1.00 |
| no_answer | 8 | cairn | abstained 5/8 | | |
| no_answer | 8 | grep | abstained 5/8 | | |
| overall | 29 | cairn | 0.97 | 0.95 | 0.93 |
| overall | 29 | grep | 0.97 | 0.95 | 0.95 |

- BM25 shows no measurable advantage over word-count grep on this set: equal Hit@3 and
  Recall@5, worse MRR (0.93 vs 0.95).
- Paraphrase failures are morphological and two-directional: FTS5 prefix matching only
  grows a token, so `caducan`, `enlaces` and `tokens` do not reach `caducidad`, `enlace`
  and `token`.
- Abstention is 5/8: the system abstains only when every term is absent. The AND→OR
  fallback answers `kafka consumer lag`, `terraform state locking` and `kubernetes
  ingress tls` with a partial match.
- Decision: keep the ranking. Details and criteria:
  [`docs/features/s6-benchmark-retrieval.md`](features/s6-benchmark-retrieval.md).

## S6.1: query stemming and stopwords (2026-11-09)

`Store.search` trims plural queries to the singular (5-character floor) and drops
stopwords before FTS5. No schema change, no rebuild. Same command and dataset:

| Category | n | System | Hit@3 | R@5 | MRR |
|---|---|---|---|---|---|
| lexical | 12 | cairn | 1.00 | 1.00 | 1.00 |
| lexical | 12 | grep | 1.00 | 1.00 | 1.00 |
| paraphrase | 10 | cairn | 0.90 | 1.00 | 0.88 |
| paraphrase | 10 | grep | 0.90 | 0.90 | 0.85 |
| multi | 7 | cairn | 1.00 | 1.00 | 1.00 |
| multi | 7 | grep | 1.00 | 0.95 | 1.00 |
| no_answer | 8 | cairn | abstained 5/8 | | |
| no_answer | 8 | grep | abstained 5/8 | | |
| overall | 29 | cairn | 0.97 | 1.00 | 0.96 |
| overall | 29 | grep | 0.97 | 0.95 | 0.95 |

- Recall@5 0.95 → 1.00 and MRR 0.93 → 0.96. Every expected memory enters the top 5.
- The 5-character floor on the stem is measured: with 4, `redis` became `redi` and
  matched `redirect_uri`.
- A two-root quorum for the OR fallback lifted abstention to 8/8 but cut paraphrase
  Hit@3 to 0.40 and overall Hit@3 to 0.79. A "2 roots or 5+ character root" variant gave
  0.94 MRR and 7/8 with an arbitrary length threshold. Both rejected; the fallback stays
  AND→OR.
- `python bench/bench_cli.py --reps 20`: search p95 135 ms, save p95 139 ms with 10k
  (idle), internal search p95 1.4 ms. SLOs unchanged.
- Details and criteria:
  [`docs/features/query-stemming-stopwords.md`](features/query-stemming-stopwords.md).

## S7: incremental sync (2026-11-09)

Two `Store` instances alternate a save and a read over 10,000 seeded memories.
`python bench/bench_sync.py --reps 40`:

| Op | p50 | p95 | max |
|---|---|---|---|
| `save` | 11.6 ms | 13.6 ms | 30.6 ms |
| `search` | 3.2 ms | 4.8 ms | 5.1 ms |

Before S7, the second writer found an unseen fingerprint and ran a full rebuild. Re-running
the alternation with an explicit `rebuild()` before each operation (10 repetitions):

| Op | p50 | p95 |
|---|---|---|
| `save` | 3,294 ms | 3,773 ms |
| `search` | 3,200 ms | 5,508 ms |

- A rebuild alone with 10k measured 3.3-3.9 s in this run. The machine is slower than the
  1.3 s pass above, so compare the two rows of this section, not against S2.
- `save` syncs before appending and applies only the new JSONL suffix. The guard is
  `jsonl_offset` plus the sha1 of the applied prefix; truncation, same-size replacement,
  a different prefix, `archive` and updates of an existing id still rebuild.
- 190 tests pass; `ruff` is clean. Details and criteria:
  [`docs/features/s7-incremental-sync.md`](features/s7-incremental-sync.md).

## 0.9.1: S7.1 and S9 verification (2026-11-10)

The gates from `AGENTS.md` were run on the release commit, on the real Windows machine:
`pytest -q` (197), `ruff check src tests bench`, `bench_cli.py --reps 20`,
`bench_mcp.py --reps 20`, `bench_sync.py --reps 40`, `bench_retrieval.py` and the golden
set.

| Metric | SLO | Measured |
|---|---|---|
| `search` end-to-end p95, 10k idle | < 350 ms | **314.5 ms** |
| `save` end-to-end p95, 10k idle (L0 included) | < 500 ms | **324.7 ms** |
| Internal `search` p95, 10k | < 10 ms | **5.7 ms** |
| MCP tool call p95, 10k (`search` / `save` / `context`) | < 50 ms | **8.3 / 21.8 / 14.8 ms** |
| Two writers, 10k (`save` / `search`) p95 | < 50 ms | **35.9 / 12.7 ms** |
| L0 `MEMORY.md` | <= 3000 chars | **2938** (1k) / **2962** (10k) |
| Precision@3, golden set | >= 0.8 | **30/30** |
| Retrieval Hit@3 / Recall@5 / MRR | report | **0.97 / 1.00 / 0.96** (grep: 0.97 / 0.95 / 0.95) |
| Abstention, 8 no-answer queries | report | **5/8** (grep: 5/8) |
| Rebuild, 10k | measure | **1.19 s** (`bench_cli`); 3.3 s on a second run under load |
| Dependencies / LLM calls | 0 / 0 | **0 / 0** |

- End-to-end at 1k: `search` p95 301.7 ms, `save` p95 336.3 ms. The floor is Python
  startup, not the store.
- **Regression found and fixed in this release:** the S9 anchor hash cache lived in the
  process and keyed on `(size, mtime_ns)`. NTFS updates `mtime` late, so a file rewritten
  with the same size reused the old hash and the L0 stopped marking it stale. The suite
  caught it on `main`; the cache now lasts one render, which still avoids reading the same
  anchor twice, and a regression test rewrites a file to the same size.
- The S7.1 re-stat is covered by a test that replaces the JSONL between the append and the
  prefix sha1: without the fix the index kept memories absent from the file.
- Details: [`docs/features/s7-incremental-sync.md`](features/s7-incremental-sync.md) and
  [`docs/DECISIONS.md`](DECISIONS.md).
