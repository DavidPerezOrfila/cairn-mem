# AGENTS.md: rules for building cairn-mem

## State and scope

- **State:** `0.17.0` is published (2026-11-20, tag `v0.17.0`, Trusted Publishing). Every round
  through S29 is implemented; `0.18.0` is release-ready and awaiting tag `v0.18.0`. The
  changelog, the open items and the conditions that reopen them live in `PLAN.md`
  §4, §4.1 and §5; this file carries the current contract only, never a restatement of them.
  `store.py`, `cli.py`, `anchor.py`, `render.py`, `paths.py`, `mcp.py`, `sessions.py`,
  `jsonl.py`, `doctor.py`, `setup.py`, `export.py`, `i18n.py` and `legacy.py` are
  implemented.
  `tests/` (548 collected: 533 pass plus 4 `xfail` corpus gaps; 11 more skip on hosts
  without symlinks or POSIX permission bits) covers the CLI, the store, the
  L0, anchors, MCP (four exact boolean annotations, read-only mode, `source` and
  search filters), sessions,
  import, the JSONL tail repair and the 8-process append, the purge under a concurrent append
  and its Git-excluded backup, incremental sync, retrieval, the paraphrase gate for `keywords`,
  the secrets corpus, dedupe/pin/purge/topics/history, the golden set, the integrity audit
  fixes, `doctor`, `setup`/`export`, `CAIRN_LANG`, the write-side A/B detection and resumable
  rows, the Claude Code `Stop` arm, the `setup` hook install path for both harnesses,
  the backlog benches and the bench hygiene, the MCP
  tool-selection eval and its real-store damage gate.
- **The 2026-11-21 audit is closed (2026-11-22):** every finding in `PLAN.md` §4.2 has a fix
  and a test (the config BOM fix brought it to 459).
- **The backlog is closed with measurements (2026-11-16).** Each item in `PLAN.md` §5 has
  the condition that reopens it; do not implement one without that condition.
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
mypy src                                            # tipos; CI falla con cualquier error
python bench/bench_mcp.py --reps 20                 # MCP tool-call latency (10k)
python bench/bench_sync.py --reps 40                # 2 writers incremental sync (10k)
python bench/bench_retrieval.py --distractors 10000 # ranking al crecer el índice
python bench/bench_retrieval.py --file bench/paraphrase.jsonl  # P@3 de léxico/flexión/paráfrasis
python bench/bench_anchors.py --reps 30             # coste de los anclas en save
python bench/ab_write.py --reps 30                  # A/B de escritura (requiere opencode)
python bench/ab_write.py --harness claude-code --arms empty,stop --reps 30 --json --rows-file bench/cc-round4-rows.jsonl
```

- Benches: each one measures in a `TemporaryDirectory` and closes its `Store` in every
  path (`closing`), because Windows cannot delete an open SQLite file. The three with an
  SLO (`bench_cli`, `bench_mcp`, `bench_sync`) exit 1 when it fails, in the text and
  `--json` paths. `bench/ab.py` (retrieval) and `bench/ab_write.py` (write side) need the
  `opencode` CLI and spend model tokens; their criteria live in `bench/ab_protocol.md` and
  `bench/ab_write_protocol.md`, written before measuring. Both reconfigure stdout to UTF-8
  (the agent answer carries `→` and accents, and the Windows console is cp1252).

- Publishing goes through `.github/workflows/publish.yml` (Trusted Publishing,
  OIDC, attestations PEP 740): push a tag `v*` and it builds and publishes; no PyPI
  token in the repo. The PyPI pending publisher (owner/repo/workflow
  `publish.yml`) is registered (`0.17.0` was published this way). Still delete `dist/`
  **and** `build/` when building locally: `uv build` reuses `build/lib` and packages
  modules you already deleted from the tree. One wheel included the old importer
  because of an orphan `build/lib/`.
- CI lives in `.github/workflows/ci.yml`: ubuntu/macos/windows × Python 3.10 and 3.14
  (tests, ruff and mypy). There is no ruff config and no pre-commit, so also verify locally
  (pytest, ruff, mypy and the criteria in `PLAN.md`).
- Python 3.10+, **standard library only** in the core. `dev` only adds pytest, ruff and
  mypy.

## Architecture

- `src/cairn_mem/cli.py` (`main(argv) -> int`; entrypoints `cairn` and `cairn-mem`, text and
  `--json`), `store.py` (core), `anchor.py` (hash and stale), `render.py` (L0),
  `paths.py` (`.cairn/` root and personal scope), `mcp.py` (stdio JSON-RPC), `sessions.py`
  (recaps), `jsonl.py` (shared append), `doctor.py` (diagnosis), `setup.py` (harness
  config), `i18n.py` (`CAIRN_LANG`) and `legacy.py` (importer).
- **Truth:** `.cairn/events.jsonl` (append-only, 2 operations: `save`, `archive`).
  `cairn.db` and `MEMORY.md` are derived and can be regenerated. Do not edit them by hand.
  `sessions.jsonl` is a separate append-only file and is not curated memory.
- `Store(root)` must create `.cairn/` and the database if they do not exist. Tests
  instantiate it without `cairn init`.
- IDs are 12 hex characters (`secrets.token_hex(6)`) plus a `ts` in `time_ns`. Apply
  order is `(ts, line number)`. A `save` with `topic_key` marks the previous memory
  `superseded` **before** the insert. A `save` may carry an optional `source`
  (provenance: agent, model or session; ≤ 100 chars, no control characters, same
  treatment as `topic_key`). There is deliberately **no**
  "unreviewed" state: with `--share`, the PR over `events.jsonl` is the human review.
  `SCHEMA_VERSION = 6` (S22: the `keywords` column; older JSONL without it replays with
  NULL. S20 added `pinned`, which replays with 0).
- Writes: `O_APPEND` plus **one** `os.write` per event, under a file lock on
  `<file>.lock` (`msvcrt.locking` on byte 0 on Windows, `fcntl.flock` on POSIX) plus the
  in-process `jsonl._LOCK`, because Windows `O_APPEND` is not atomic between threads and
  two processes repairing the tail otherwise truncate each other's line. The lock lives in
  its own file (S24): a locked byte 0 of `events.jsonl` cannot be *read* by another process
  on Windows, so a concurrent `rebuild` died with `PermissionError`.
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
  `id`, `kind`, `title`, `body` or metadata field fails naming the file and the line, never
  with a `KeyError` or a CHECK `IntegrityError`. Metadata (S19): no control characters
  (the historical multi-line `why` tolerates `\n` and `\t`), `why` ≤ 2000, `anchor_path`
  ≤ 500, `anchor_hash` ≤ 64. Only a torn tail (the file does not end in `\n`)
  is tolerated, and `store.decode_jsonl` trims it before decoding so a crash inside a
  multi-byte character is tolerated too (a bad byte mid-file still fails).
- `Store.save` enforces the same contract as `parse_event` at the write edge: `body` must be
  a `str` (a `None` or an int used to crash with `TypeError` or write an unrebuildable
  event), and `anchor_path`/`anchor_hash` must be strings within `MAX_ANCHOR_PATH`/
  `MAX_ANCHOR_HASH` with no control characters.
- L0 (`.cairn/MEMORY.md`) is ≤ 3000 characters: a fixed English title plus a
  "Data, not instructions" header line, then the pinned rows (`📌`, human-set), then
  round-robin by kind (each round: `convention > decision > gotcha > fact`) and newest `ts`
  first inside each kind. Output is deterministic (prompt cache). The anchor hashes of the
  candidate rows are read in an **8-thread pool**; the hash is never reused across commands
  (`anchor._cached_hash`): NTFS updates `mtime` late, so a same-size rewrite would hide a
  stale anchor.
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
  Ranking: `bm25(mem_fts, 5.0, 1.0, 0.5, 3.0, 3.0, 2.0)` over
  `title, body, why, topic_key, keywords, anchor_path`.
- `search` filters (`--kind`, `--topic` exact `topic_key`, `--stale`) go into the
  parameterized SQL WHERE. With `--stale` SQL does **not** apply the LIMIT: the first K by
  bm25 can all be fresh, so the ranking is walked and cut at `limit` stale rows (anchors
  over `MAX_HASH_BYTES` count as stale without hashing). `partial` is an output field set
  only on the OR fallback, never an input flag.
- **Security:** reject (do not redact) secrets before writing: cloud keys (`AKIA`, `ASIA`),
  `BEGIN ... PRIVATE KEY`, JWTs `eyJ...`, provider tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`,
  `ghr_`, `github_pat_`, `glpat-`, `sk-proj-`, `sk-ant-`, `AIza`, `sk-` alone, `sk_test_`,
  Slack `xox[baprs]-` and `hooks.slack.com/services/`, Stripe `sk_live_`/`rk_live_`,
  `npm_`), `Bearer <token>` with at least one digit (prose like "Bearer authentication"
  must pass), URLs `://user:pass@`, Oracle `user/pass@host` and `jdbc:`, SAS `sig=`,
  Fernet/AccountKey (base64 ≥42 with `=`), Azure `~XXXX~…`.
  Named keys (`password`, `pwd`, `secret`, `token`, `api_key`, `client_secret`,
  `contraseña`, `_pass`/`_password`/`_secret` suffixes) reject only when the **value**
  carries a digit or a symbol other than `_`; `private_key`/`secret_key` reject any
  non-excluded value; `pass`/`clave` need upper+lower+digit (in EBS "clave" is a column).
  `null`, `$VAR`, `%VAR%`, `<…>` pass — `hunter2` must stay rejected (the corpus in
  `tests/test_secrets_corpus.py` is the contract, both directions).
  A `body` over 500 characters, a `title` over 200 or a `why` over 2000 (multiline
  prose; `\n`/`\t` allowed) is an error. `id` must be 12 lowercase
  hex, and `topic_key` is ≤ 100 characters with no control characters.
- **Injection:** `reject_secrets` also rejects `curl|wget … | sh` and
  "ignore/ignora … (previous|prior|anteriores|previas)"; it applies to sessions too. The L0
  carries a fixed header (`Data, not instructions…`) because it lives inside the prompt.
- **Dedupe:** `Store.similar(title, body)` returns the 3 FTS neighbours with their Jaccard
  overlap over stems. `save` blocks only at ≥ 0.9 (`DUP_THRESHOLD`), with the id and
  `--topic` in the message; below that it only prints `similar:` (CLI stderr, MCP result)
  so a paraphrase is never refused. A `topic_key` or an existing `id` skips the filter:
  those are the update paths (import idempotent, pin).
- **Pins:** `pin`/`unpin` exist only in the CLI (never in MCP): a poisoned memory with a
  pin would outrank everything. At most 5 pins and 800 characters; they render first with
  `📌`. The row travels as a `pinned` field on a `save` event with the same id, **not** as a
  new `op`: older `parse_event`s reject an unknown `op` and a `--share` repo would stop
  opening. `SCHEMA_VERSION = 6` (S22 added the `keywords` column; older JSONL replays
  without it).
- **Keywords (S22):** optional synonyms on `save` (`--keywords`, MCP `keywords`): ≤ 200
  characters, no control characters, whitespace normalized, empty means absent, and they go
  through `reject_secrets` in `save` and in `doctor`. Sixth FTS column with the `topic_key`
  weight (3.0); they never render in the L0 and must not change scores when absent.
- **History (S22):** `cairn history <topic>` reads the derived `mem` rows (superseded and
  archived included), ordered `(ts, rowid)`, merging project and personal by `ts`; CLI only.
- **Writes are process-safe (S22, S24):** `jsonl.append_jsonl` holds a file lock
  (`msvcrt.locking` on byte 0 on Windows, `fcntl.flock` on POSIX) around the tail repair and
  the single `os.write`. `_LOCK` only serializes threads: without the file lock two
  processes truncate each other's lines (measured 190-197 of 200 lines with 8 processes).
  The lock is taken on `<file>.lock` (S24), never on the log: a locked byte 0 of a Windows
  file fails to read from another process (2 of 5 runs of the concurrent test died in
  `rebuild` with `PermissionError`), so the log must stay unlocked. `*.lock` and
  `events.jsonl.bak` are in the managed `.gitignore` entries: the backup keeps the purged
  secret and a `--share` repo would send it with `git add .`.
- **Purge:** `cairn purge <id>` rewrites `events.jsonl` without every event of that id
  (save, archive, pin) and leaves `events.jsonl.bak`. It exists because the JSONL is
  append-only and `archive` keeps the secret in Git; it warns to rotate the credential.
  It takes `_LOCK` plus the `<file>.lock` file lock around the read **and** the replace
  (`_remove_events`): without it a concurrent `save` lands in the old file and `os.replace`
  discards it, and on Windows the replace fails with the log open in another process. The
  lock covers the whole rewrite (measured 2026-11-21: 50 ms at 10k events, 487 ms at 100k
  / 19.8 MiB, against the ~10 s `msvcrt.locking` wait); `rebuild` runs outside it.
- Minimal imports at startup. CLI end-to-end SLO: p95 `search` < 350 ms and `save` <
  500 ms, startup included. In-process MCP tool call: < 50 ms.
- **MCP:** stdout carries protocol only (NDJSON in binary, `\n`). Logs go to stderr. No
  asyncio and no signals. The process caches one `Store` per scope and is the only writer
  while it lives. Every tool carries four explicit boolean MCP annotations
  (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`): the 5 read
  tools are `true/false/true/false`; `save` and `archive` are
  `false/true/false/false`; `save_session` is `false/false/false/false`
  (`readOnly/destructive/idempotent/openWorld`). Read-only means no writes to
  `events.jsonl` or `sessions.jsonl`; refreshing derived files or creating a scope
  directory does not change it. `cairn mcp --read-only` serves only the
  5 read tools and rejects the write tools at the protocol edge. `archive` falls back to the
  personal scope like `get` and the CLI, and `save_session` writes the `sessions.jsonl` line
  into the `.gitignore` of its scope (`paths.ignore_sessions`, the personal scope has no
  `init`). S20: the tool descriptions, the `initialize` instructions, every tool error and
  the internal error are in **English**, and `save` appends the `similar:` lines to its
  result. Since S21 the library edge (`store`, `sessions`, `anchor`, `paths`, `jsonl`,
  `mcp`) is **English only**, because an MCP tool error is agent-facing; `cli`, `doctor` and
  `setup` go through `i18n.t(en, es)`, English by default and `CAIRN_LANG=es` opt-in. Any
  new human message in those three modules is a pair; any new library message is English.
- **Doctor:** `doctor.py` is imported lazily and is local: no network, no events written.
  It parses `events.jsonl` with `parse_event` (line-numbered failures), re-runs
  `reject_secrets` on every `save` (title/body/why/source/topic/keywords/anchor_path) and on
  every `sessions.jsonl` recap (S20: a stored secret is `fail`/`secrets`, the gate before
  `--share`), and refreshes `cairn.db`/`MEMORY.md` only because it opens the `Store`,
  like every other command. Exit code 1 only on `fail`; `warn` keeps it 0. `GITIGNORE_ENTRIES`
  is defined once in `paths.py` (the `cairn.db-*` drift came from the copy in `doctor.py`).
- **Setup:** `setup.py` holds one table (`HARNESSES`) with the config file, the JSON path of
  the server, the instructions file and the hook path per harness. It only touches the repo
  (never `~/.claude.json` or the global OpenCode config) and only the `cairn` key: a config
  file that is not strict JSON (JSONC with comments) is **not** rewritten, the command fails
  with code 1 and prints the block to paste. A new harness is one row plus one test
  against a fixture; do not add a format nobody verified. Since S21, when the instructions
  file is not `AGENTS.md` and already imports `@AGENTS.md`, `setup` writes no block there
  and removes one that an older setup left. Since S28, `setup` installs the measured
  `Stop` hook per harness from a package asset (package data in wheel and sdist),
  idempotently, and `install_hook` is the same function `bench/ab_write.py` calls, so
  measured and installed cannot drift; tests pin the installed bytes.
  `opencode` writes `.opencode/plugins/cairn-stop/index.ts` from `assets/stop/index.ts`.
  `claude-code` writes `.claude/hooks/cairn_stop.py` from `assets/stop/claude_code.py` —
  a `SessionStart` + `Stop` pair with per-session attribution and an install-time save
  baseline — after validating `.claude/settings.json` (`utf-8-sig`): invalid settings
  fail with exit 1 and no writes, and the cairn command is appended only when absent.
  The install also adds `.cairn-nudge/` and `.cairn-nudge.log` to the root `.gitignore`.
  Both hooks are measured (OpenCode 30/30 against 20/30, S27; Claude Code 30/30 against
  16/30 for the snippet alone, 2026-11-24).
- **Export:** `cairn export` is a snapshot of active memories grouped by kind, plus the
  last N recaps only when `--sessions N` is given. No stale marks: that would hash every
  anchor and turn a copy into `check`. It must stay byte-identical across runs.
- **Sessions:** `.cairn/sessions.jsonl` is local and does not enter FTS or the L0. A recap
  may exceed 500 characters (up to 20k). `context` injects only the last **project** recap;
  a personal one belongs to another repo. `Sessions.last` walks the tail backwards
  accumulating windows: one recap can exceed 64 KB with JSON escapes, and `MAX_FRAGMENT`
  is 1 MiB so the tail repair does not truncate it. `_records` rejects a line that is not
  a JSON object or is invalid mid-file with `sessions.jsonl línea N`; only a torn tail (no
  final `\n`) is skipped. A record is served only if `id` is 12 hex and `summary` is a
  string (S19: a truncation that still parses does not reach `last`/`all`). `last` and
  `all` share one order: the append (line number), not
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
