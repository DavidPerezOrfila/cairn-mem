# AGENTS.md: rules for building cairn-mem

## State and scope

- **M6-M9 are closed; S1-S7.1, S9, S9.1, S10, S10.1, S11 and S13 are implemented.** 0.11.0 is
  published (2026-11-12, tagged `v0.11.0`). `store.py`, `cli.py`, `anchor.py`,
  `render.py`, `paths.py`, `mcp.py`, `sessions.py`, `jsonl.py`, `doctor.py` and
  `legacy.py` are implemented. `tests/` (245) covers the CLI, the store, the L0, anchors,
  MCP, sessions, import, the JSONL tail repair, incremental sync, retrieval, the golden
  set, the integrity audit fixes and `doctor`.
- **Keep this file current in the same change:** version and release state, test count,
  modules, commands and rules. A stale `AGENTS.md` is a defect, not a chore.
- Implement **one round (S#) or milestone (M#) at a time**, and only that one. Read
  `PLAN.md` and `docs/DESIGN.md` before writing code.
- Tests fix the exact API, including the docstring in `store.py`. Do not relax them to get
  green.
- The next thing comes from the **backlog**, and only with a measurement that justifies
  it.

## Setup and commands

```bash
pip install -e ".[dev]"                            # required; without it pytest fails with ModuleNotFoundError
pytest -q
pytest tests/test_store.py::test_save_and_get -q   # one test
ruff check src tests bench
python bench/bench_mcp.py --reps 20                 # MCP tool-call latency (10k)
python bench/bench_sync.py --reps 40                # 2 writers incremental sync (10k)
```

- Before publishing: delete `dist/` **and** `build/`. `uv build` reuses `build/lib` and
  packages modules you already deleted from the tree. One wheel included the old importer
  because of an orphan `build/lib/`.
- CI lives in `.github/workflows/ci.yml`: ubuntu/macos/windows × Python 3.10 and 3.14
  (tests and ruff). There is no ruff config and no pre-commit, so also verify locally
  (pytest, ruff and the criteria in `PLAN.md`).
- Python 3.10+, **standard library only** in the core. `dev` only adds pytest and ruff.

## Architecture

- `src/cairn_mem/cli.py` (`main(argv) -> int`; entrypoints `cairn` and `cairn-mem`, text and
  `--json`), `store.py` (core), `anchor.py` (hash and stale), `render.py` (L0),
  `paths.py` (`.cairn/` root and personal scope), `mcp.py` (stdio JSON-RPC), `sessions.py`
  (recaps), `jsonl.py` (shared append), `doctor.py` (diagnosis) and `legacy.py` (importer).
- **Truth:** `.cairn/events.jsonl` (append-only, 2 operations: `save`, `archive`).
  `cairn.db` and `MEMORY.md` are derived and can be regenerated. Do not edit them by hand.
  `sessions.jsonl` is a separate append-only file and is not curated memory.
- `Store(root)` must create `.cairn/` and the database if they do not exist. Tests
  instantiate it without `cairn init`.
- IDs are 12 hex characters (`secrets.token_hex(6)`) plus a `ts` in `time_ns`. Apply
  order is `(ts, line number)`. A `save` with `topic_key` marks the previous memory
  `superseded` **before** the insert.
- Writes: `O_APPEND` plus **one** `os.write` per event. There is an in-process lock
  (`jsonl._LOCK`) because Windows `O_APPEND` is not atomic between threads.
- When the database opens, it compares `(size, mtime_ns)` of the JSONL and
  `PRAGMA user_version`. If they differ, it rebuilds automatically (this covers
  `git pull`).
- **Sync:** after the fingerprint changes, `_sync` applies only the JSONL suffix when
  `jsonl_offset` and the sha1 of the applied prefix match. It rebuilds on truncation, a
  same-size replacement, a different prefix, `archive`, an update of an existing id or a
  duplicate id in the batch: their result depends on the global `ts` order, not on append
  order. `save` syncs before appending; never add a rebuild per append. The prefix is
  certified only if a re-stat after its sha1 still matches the fingerprint; otherwise the
  read rebuilds (S7.1). A **complete** JSON line without the final `\n` (another writer,
  a `git checkout`) is applied and certified; certifying it unapplied lost it forever.
- `stale` is calculated when reading. It is not persisted, and there is no verification
  event.
- Every JSONL line goes through `store.parse_event` before it reaches SQLite: a bad `op`,
  `id`, `kind`, `title` or `body` fails naming the file and the line, never with a
  `KeyError` or a CHECK `IntegrityError`. Only a torn tail (the file does not end in `\n`)
  is tolerated.
- L0 (`.cairn/MEMORY.md`) is ≤ 3000 characters. It goes round-robin by kind (each round:
  `convention > decision > gotcha > fact`) and newest `ts` first inside each kind. Output
  is deterministic (prompt cache).
- Project root: search for `.cairn/` upward from the cwd, or use `CAIRN_DIR`. The search
  excludes `~/.cairn` and `CAIRN_HOME` (the personal scope). Personal scope:
  `CAIRN_HOME` or `~/.cairn`.

## Non-obvious rules

- **Windows first:** every file uses `encoding="utf-8"` and JSON uses
  `ensure_ascii=False`. Anchor paths are POSIX paths relative to the root. The sha1 hash
  normalizes CRLF to LF; otherwise you get false stale flags between OSes. `os.open` for
  the JSONL needs `O_BINARY`; otherwise Windows turns `\n` into `\r\n`. `Path.write_text`
  always passes `newline="\n"` (`.gitignore` included): the default writes CRLF on
  Windows. Commits use LF: `.gitattributes` sets `eol=lf`, so do not rely on the clone's
  `core.autocrlf`.
- **FTS5:** never pass raw text to `MATCH`. Sanitize it (`\w+` → `"t"*`, stopwords
  out, plural trimmed to 5+ characters, prefix), use AND and fall back to OR when there
  are no results. Raw queries fail with `-`, `:` and `"`.
  Ranking: `bm25(mem_fts, 5.0, 1.0, 0.5, 3.0, 2.0)`.
- **Security:** reject (do not redact) secrets before writing: cloud keys (`AKIA`, `ASIA`),
  `BEGIN ... PRIVATE KEY`, JWTs `eyJ...`, provider tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`,
  `ghr_`, `github_pat_`, `glpat-`, `sk-proj-`, `sk-ant-`, `AIza`, Slack `xox[baprs]-`,
  Stripe `sk_live_`/`rk_live_`, `npm_`), `Bearer <token>` with at least one digit (prose
  like "Bearer authentication" must pass),
  `password|secret|token|api_key` with `=` or `:` (JSON/YAML), and URLs `://user:pass@`.
  A `body` over 500 characters or a `title` over 200 is an error. `id` must be 12 lowercase
  hex, and `topic_key` is ≤ 100 characters with no control characters.
- Minimal imports at startup. CLI end-to-end SLO: p95 `search` < 350 ms and `save` <
  500 ms, startup included. In-process MCP tool call: < 50 ms.
- **MCP:** stdout carries protocol only (NDJSON in binary, `\n`). Logs go to stderr. No
  asyncio and no signals. The process caches one `Store` per scope and is the only writer
  while it lives.
- **Doctor:** `doctor.py` is imported lazily and is local: no network, no events written.
  It parses `events.jsonl` with `parse_event` (line-numbered failures) and refreshes
  `cairn.db`/`MEMORY.md` only because it opens the `Store`, like every other command.
  Exit code 1 only on `fail`; `warn` keeps it 0.
- **Sessions:** `.cairn/sessions.jsonl` is local and does not enter FTS or the L0. A recap
  may exceed 500 characters (up to 20k). `context` injects only the last **project** recap;
  a personal one belongs to another repo. `Sessions.last` walks the tail backwards
  accumulating windows: one recap can exceed 64 KB with JSON escapes, and `MAX_FRAGMENT`
  is 1 MiB so the tail repair does not truncate it. `_records` rejects a line that is not
  a JSON object or is invalid mid-file with `sessions.jsonl línea N`; only a torn tail (no
  final `\n`) is skipped. `last` and `all` share one order: the append (line number), not
  `ts`; a duplicate `id` keeps its last line. `id` must be 12 lowercase hex in `save` and
  `get`. `context` keeps the head and the tail (2000 + 2000 characters) of a long recap.
- **Importer:** idempotent through `sha1("<fixed salt>:<source id>")[:12]`. `What` →
  `body` (≤ 500) and the rest → `why`. `global/personal` goes to the personal scope, not
  to the current repo.
- No LLM in any path. Nothing from the backlog (`hits`, decay, sqlite-vec, passive git
  hook) without a measurement that justifies it.
- A design change needs a row in `docs/DECISIONS.md` (date, decision, reason).
- Dogfooding: as soon as M1 works, save the project decisions with `cairn`.

## Definition of done (per milestone)

1. Tests for the milestone pass, and so do the tests from earlier milestones (a skipped
   test does not count).
2. The acceptance criteria in `PLAN.md` are measured and written down.
3. The milestone checklist in `PLAN.md` is ticked.
4. `AGENTS.md` reflects the new state in the same commit (version, release, test count,
   modules, rules).
