# PLAN v2: cairn-mem (revised)

> Persistent memory for coding agents: effective, with no latency or cost penalty, and
> portable to any harness with a shell.
> **Estimate: 4-6 days** (down from 6-9). One milestone is one agent session. Flow:
> understand → red test → implement → measure → tick.

## 1. Review: weak points and what changed

| # | Weak point in plan v1 | Change |
|---|---|---|
| 1 | The SLO "p95 < 10 ms" ignored **Python startup**, which is what the agent actually feels | End-to-end SLO with startup included (M4 revised it to `search` < 350 ms and `save` < 500 ms after measuring the real floor) |
| 2 | `stale` persisted through a `verify` event: it depends on the checkout and diverges between branches | **Calculated when reading**, only for returned results. No event, no state |
| 3 | Anchor hash differed between Windows and Linux (CRLF), causing false stale flags | Hash with **CRLF→LF**. Anchor path is POSIX and relative |
| 4 | `hits` through an event on every `get`: reading becomes writing (latency, Git noise) | **Out of v0.1** (backlog). L0 uses `kind` priority plus recency |
| 5 | Raw FTS5 queries **fail** with `-`, `:` and `"` (tested: `oauth-callback` raises an error) | Required sanitizing: `"t"*` per term, **AND and OR if empty** |
| 6 | Database out of date after `git pull` (nobody rebuilt it) | JSONL fingerprint `(size, mtime_ns)` → automatic `rebuild`. `user_version` also triggers a rebuild |
| 7 | Secret scrubbing in M5 was late: the JSONL may go to Git | **M1**, and by **rejection** (no silent redaction) |
| 8 | `MEMORY.md` versioned and regenerated → conflicts and noise | Derived and gitignored. Regenerated on `save/archive`/rebuild, without hooks |
| 9 | Memory in Git by default in a corporate environment | **Local-only by default**. `cairn init --share` versions it |
| 10 | File lock (`msvcrt`/`fcntl`): complex and not very portable | `O_APPEND` plus **one** `os.write` per event |
| 11 | Own ULID, 6 event types, `scope`/`last_verified`/`hits` columns | 12-hex id plus `ts`. **2 events** (`save`, `archive`). Minimal schema |
| 12 | BM25 × boosts, lexical dedupe, decay, promotion, LLM `--propose` | Only `bm25()` with column weights. The rest goes to the **backlog** |
| 13 | Passive capture through a git hook: noise that lowers precision | Out. An explicit rule for **what to save and what not** in `docs/AGENT_SNIPPET.md` |
| 14 | Hand-written MCP with a global scope: cost and risk without proven need | **Backlog**. The CLI covers any harness with a shell |
| 15 | Windows: `export.sh` needs bash, cp1252 encoding, no `init` and no project root | Cross-platform export (standard library). Forced UTF-8 plus a test. `cairn init`. Search `.cairn/` upward |
| 16 | A/B of 10-20 tasks: noisy and expensive | **Golden set** for retrieval (no LLM, in CI) plus a small **paired** A/B |
| 17 | `get` by long ID (ULID) is error prone for an agent | Short 12-hex ID |

## 2. Measurable goals (SLOs)

| Metric | Target |
|---|---|
| `cairn search` end-to-end (Python startup included), p95 | **< 350 ms** idle, 10k (previously 150 ms; see below) |
| `cairn save` end-to-end (L0 render included), p95 | **< 500 ms** idle, 10k (previously 200 ms) |
| Internal `search` query (10k records) | **< 10 ms** |
| In-process MCP tool call (10k records) | **< 50 ms** |
| L0 (`MEMORY.md`) | **≤ 3000 characters** (about 900 tokens) |
| Precision@3 on the golden set | **≥ 0.8** |
| Rebuild with 10k events | measure (measured: 1.3 s idle) |
| Dependencies / LLM calls | **0 / 0** |

> Revised on 2026-11-02 after measuring the startup floor: `python -c pass` is about 72 ms,
> and importing only `sqlite3, json, re` is about 138 ms. The original 150/200 ms were out
> of reach without a daemon or a native binary. See `docs/BENCHMARKS.md`.

## 3. Milestones

### M0: Bootstrap ✅
- [x] Structure, `pyproject.toml`, `AGENTS.md`, design, schema, `AGENT_SNIPPET.md`
- [x] Red tests for M1 plus the M2 tests (they stay skipped until the module exists)

**Acceptance:** `pip install -e ".[dev]" && pytest -q` → M1 red, M2 *skipped*.

### M1: Core (1-2 days) ✅
- [x] `Store`: `save/get/search/archive/rebuild/dump` as described in `docs/DESIGN.md`
- [x] Append-only JSONL (`O_APPEND` plus 1 `os.write`), UTF-8 without BOM,
  `ensure_ascii=False`
- [x] Event application: `topic_key` marks the previous memory `superseded` **before**
  the insert. Order is `(ts, line number)`
- [x] JSONL fingerprint and `user_version` → automatic rebuild
- [x] Reject secrets and `body > 500`
- [x] Sanitized search AND→OR, `bm25(mem_fts,5.0,1.0,0.5)`, snippet
- [x] CLI: `init [--share]`, `save`, `search`, `get`, `archive`, `rebuild` (text and
  `--json`). Root `.cairn/` upward or `CAIRN_DIR`
- [x] Fast startup: minimal imports, no heavy imports at the beginning

**Acceptance:** `tests/test_store.py` passes. `rebuild` is idempotent. Internal `search`
< 10 ms with 10k synthetic records (measured 2026-11-01: rebuild 507 ms, `search` p95
3.87 ms).
**Dogfooding:** from here on, save the project decisions with `cairn`.

### M2: L0 and anchors (1 day) ✅
- [x] `anchor.py`: `file_hash` (CRLF→LF), `is_stale`
- [x] `render.py`: deterministic `render_l0(store, max_chars=3000)`, order
  `convention > decision > gotcha > fact` and newest `ts` first, `⚠ revisar` on stale
- [x] `search` returns `stale` per result. `cairn render` and `cairn check`
- [x] Automatic `MEMORY.md` regeneration after `save/archive/rebuild`

**Acceptance:** `test_anchor.py` and `test_render.py` pass. L0 output is byte-identical
when nothing changes (prompt cache). `check` over 1k records < 1 s.
(measured 2026-11-02: 53 tests passed, L0 2,944 characters with 1k records and stable
when reopened, `check` end-to-end 181 ms, `render` 135 ms)

### M3: Integration (0.5-1 day) ✅
- [x] `docs/AGENT_SNIPPET.md` tested in **at least 2 harnesses** (for example Claude Code
  and OpenCode): save in one, recover in the other
- [x] Install: `pipx install .` (Windows included), and check that `cairn` ends up on PATH
- [ ] Optional: a Claude Code `Stop` hook that reminds the agent to save (only if we
  measure that the agent does not save)

**Acceptance:** save → new session → recover works in 2 harnesses.

**Measured 2026-11-02:**
- `pipx install .` → `cairn-mem 0.0.1`. Shim `~/.local/bin/cairn.exe` with `render` and
  `check`.
- OpenCode saved `6146ba141640` (`decision`, topic `vcs/lf`), and GitHub Copilot CLI
  recovered it with `cairn search`.
- Copilot CLI saved `bd4076114207` (`convention`, topic `git/commits`), and a new OpenCode
  session recovered it.
- `Stop` hook: not installed. There is no evidence that the agent does not save (it is
  measured in the M4 A/B).

### M4: Measurement and release (1 day) ✅
- [x] `bench/bench_cli.py`: p50/p95 end-to-end for `search` and `save` with 1k and 10k
  records (on real Windows)
- [x] `bench/golden.jsonl` (about 30 queries) plus a precision@3 test in CI
- [x] **Small paired A/B:** 8 tasks × 2 arms (without and with memory), same model,
  2 repetitions. Metrics: total tokens, tool calls, success, human interventions. With
  such a small n it is **indicative**, not conclusive
- [x] Reserve or publish `cairn-mem` on PyPI (free on 2026-10-31; check again before) and
  verify that the `cairn` command does not clash on PATH
- [x] Final README, version 0.1.0, Git tag

**Acceptance:** the §2 SLOs are written in `docs/BENCHMARKS.md`, with an explicit decision:
do we need to change the L0, ranking or save rules?

**Measured 2026-11-02:**
- 1k/10k benchmark in [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md). Precision@3: 30/30 = 1.00.
- End-to-end SLO revised to `search` < 350 ms and `save` < 500 ms after measuring the
  startup floor (`python -c pass` 72 ms, imports 138 ms). Idle: search p95 304 ms, save
  p95 451 ms, internal query 5.9 ms → **passes**.
- Decision: **do not** touch the L0, ranking or save rules. Optimizing startup stays in
  the backlog, only with evidence of use.
- A/B: without memory 0/16 correct and 26,826 tokens. With memory 16/16 and 20,982 tokens
  ([`docs/AB_RESULTS.md`](docs/AB_RESULTS.md)).
- `uv build` plus installing the 0.1.0 wheel in a clean venv: `init`, `save`, `search` and
  `render` work.
- PyPI: **published 2026-11-02** (`cairn_mem-0.1.0` wheel and sdist,
  https://pypi.org/project/cairn-mem/0.1.0/). `pip index versions cairn-mem` → 0.1.0.
  Installing from PyPI in a clean venv verified. `cairn` on PATH with no clash (pipx shim
  plus editable).

### M5: MCP stdio and cross-platform CI ✅
- [x] `mcp.py`: JSON-RPC 2.0 over NDJSON on stdio, no SDK and no dependencies
- [x] 4 tools (`save`, `search`, `get`, `context`). The rest stays in the CLI
- [x] Cached `Store`: one process, one writer, no Python startup per call
- [x] `cairn mcp` as a subcommand. Nothing is written to stdout outside the protocol
- [x] CI: ubuntu/macos/windows × Python 3.10 and 3.14 (tests and ruff)
- [x] `bench/bench_mcp.py` for tool-call latency with 10k
- [x] Fix: `_known_size` was not updated after `save`/`archive`, so every write in a long
  process triggered a full rebuild
- [x] L0 limited in SQL (`active_ordered`) instead of sorting every row in Python

**Acceptance:** tool call p95 < 50 ms (measured 2026-11-02: search 4.0 ms, save 37.4 ms,
context 18.4 ms with 10k). 66 tests pass. `ruff` is clean. All 6 CI cells pass.

### M6: Sessions (0.5 day) ✅
- [x] `sessions.jsonl` append-only in `.cairn/`, separate from curated memory
- [x] `Sessions`: `save/list/get`. Reopen the process and recover the recap
- [x] CLI `cairn session save|list|get` and MCP tool `session`
- [x] Long recap (no 500-character limit) without touching the L0

**Acceptance:** a recap of about 2k characters is saved and recovered. `MEMORY.md` does
not change. The JSONL tolerates a torn last line like `events.jsonl`.
(measured 2026-11-03: 5k recap saved and recovered, 84 tests passed)

### M7: Personal scope (0.5 day) ✅
- [x] `paths.personal_dir()`: `CAIRN_HOME` or `~/.cairn`
- [x] `save/search --personal`. `get` looks in the project and the personal scope
- [x] MCP: `scope` (`project|personal`) in `save` and `search`

**Acceptance:** a personal memory is recovered from another repo and does not appear in
the project L0. The project keeps working without `CAIRN_HOME`.
(measured 2026-11-03: `--personal` with a temporary `CAIRN_HOME`. The project L0 does not
include it)

### M8: Legacy importer (1 day) ✅
- [x] `cairn import legacy --db PATH [--dry-run]`
- [x] Mapping: `What`→`body`, `Why/Where/Learned`→`why`. Type→`kind`.
  `session_summary`→session
- [x] `project` → the repo `.cairn/` (by provenance). `global/personal` → `~/.cairn`
- [x] Idempotent: id derived from the source id with a fixed salt. Deleted and superseded
  rows are skipped

**Acceptance:** imports the 64 real observations with no duplicates when re-run. Secrets
are rejected per row and reported, without aborting the batch.
(measured 2026-11-03: 23 memories plus 10 sessions. Second pass 0 + 0 with 33 skipped)

**0.2.0 release:** 2026-11-03 on PyPI (wheel and sdist) and tag `v0.2.0`. A clean install
from PyPI was verified with `init`, `save`, `session`, `search` and `import --dry-run`.

### M9: Closing parity gaps ✅
- [x] `Sessions.save` rejects secrets (before, `sessions.jsonl` accepted them)
- [x] MCP `context` returns the L0 plus the last session recap (≤ 4000 chars), without
  touching `MEMORY.md`
- [x] `Store` reapplies the JSONL on reads when the fingerprint changed (long-lived MCP
  after `git pull` or the CLI)
- [x] Global binary reinstalled: `pipx install . --force` serves the 5 tools
- [x] Importer renamed to `legacy` (module, subcommand and docs). The remote repo does not
  name the tool it replaces

**Acceptance:** 94 tests pass. `ruff` is clean. `tools/list` from `cairn mcp` shows
`save, search, get, context, session`, with `context` describing the session recap.
(measured 2026-11-03: 94 passed. A read with no changes does not trigger a rebuild)

**0.2.1 release:** 2026-11-03 on PyPI (wheel and sdist, `uv build` plus `uv publish`).

**0.2.2:** the session MCP tool becomes `save_session` (OpenCode filtered `session`
because of a name collision, and the agent could not save the recap).

## 4. Improvement rounds (one per release)

Each round is a slice: tests first, gate, review and its own release.

| Round | Improvement | Release | Evidence |
|---|---|---|---|
| S1 | L0 shares the budget across kinds (round-robin) | 0.3.0 | [`docs/features/l0-fair-share.md`](docs/features/l0-fair-share.md) |
| S2 | `topic_key` visible in the L0 and `search`. FTS indexes `topic_key` and `anchor_path` | 0.4.0 | [`docs/features/topic-visibility.md`](docs/features/topic-visibility.md) |
| S3 | Cross-scope `search` (project plus personal) and the project session in `context` | 0.5.0 | [`docs/features/transversal-search.md`](docs/features/transversal-search.md) |
| S4 | `archive` over MCP and reading older sessions | 0.6.0 | [`docs/features/mcp-archive-session-history.md`](docs/features/mcp-archive-session-history.md) |
| S5 | Durability and security: torn tail, same-size replacement, prefixed tokens, validated `id`/`topic` | 0.7.0 | [`docs/features/s5-durabilidad-seguridad.md`](docs/features/s5-durabilidad-seguridad.md) |
| S6 | Honest retrieval benchmark (Hit@3/R@5/MRR/abstention, grep baseline) | — (no runtime change) | [`docs/features/s6-benchmark-retrieval.md`](docs/features/s6-benchmark-retrieval.md) |
| S6.1 | Query-side plural stem and stopwords; two-root quorum measured and rejected | 0.8.0 | [`docs/features/query-stemming-stopwords.md`](docs/features/query-stemming-stopwords.md) |
| S7 | Incremental sync: apply only the JSONL tail, guarded by the offset and the prefix sha1 | 0.9.0 | [`docs/features/s7-incremental-sync.md`](docs/features/s7-incremental-sync.md) |
| S7.1 | Certification re-stat: a prefix replaced during the sha1 forces a rebuild | 0.9.1 (pending) | [`docs/DECISIONS.md`](docs/DECISIONS.md) |
| S9 | Audit fixes: one `_session_root`, anchor hash cache, anchor size cap, tail read for `context`, `search --personal` without side effects, `.MEMORY.md.*` ignored | 0.9.1 (pending) | `docs/DECISIONS.md` |
| S8 | GitHub Sponsors metadata (`.github/FUNDING.yml` and the `Funding` URL) | pending | Deferred 2026-11-10: the GitHub listing must exist first |

**0.8.0 release:** 2026-11-09 on PyPI (wheel and sdist) and tag `v0.8.0`. Verified with a
clean install (`init`, `save`, `search`, `session`).

**0.9.0 release:** 2026-11-10 on PyPI (wheel and sdist) and tag `v0.9.0`. Verified with a
clean install from the public index (`init`, `save`, `search`).

## 5. Backlog (only with measured evidence)

- `hits` in a local, non-versioned table plus a ranking boost (if the golden set or the A/B
  shows bad prioritization)
- `compact`/decay (if the number of active memories hurts precision)
- `sqlite-vec` (if precision@3 is < 0.8 because of synonyms and titles do not fix it)
- Passive capture through a git hook (only if the agent does not save and the noise is
  acceptable)
- `anchor_cache` table in `cairn.db` (`path`, `size`, `mtime_ns`, `sha1`): the anchor hash
  cache is in-process only, so a one-shot CLI command still hashes each anchored file once.
  Only if `save` p95 passes 500 ms with many large anchors

## 6. Risks (the ones left)

| Risk | Mitigation |
|---|---|
| The agent does not save memories | Clear rules in the snippet plus an optional `Stop` hook. Measure in the A/B |
| The agent saves junk | A "do NOT save..." rule, a 500-character limit and `topic_key` to replace old entries |
| Stale due to a whole-file anchor (false positives on large files) | It only warns (`⚠ revisar`), it does not hide. Measure the rate in the A/B. Anchor to the most specific file |
| Windows startup latency (antivirus, pipx shim) | Measure end-to-end in M4. Minimal imports |
| Out-of-date memory after `git pull` | JSONL fingerprint plus automatic rebuild |
| Secrets | Rejection on write plus local-only by default |
| FTS5 missing in some Python build | Check at startup and fail with a clear message |

## 7. Startup prompt for the agent

```text
Read AGENTS.md, PLAN.md and docs/DESIGN.md. Implement ONLY M1 with TDD
(tests/test_store.py is already red). Standard library only. Show the real pytest
output, tick the M1 checklist in PLAN.md and do not move on to M2.
```
