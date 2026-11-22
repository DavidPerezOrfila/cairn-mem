# PLAN v2: cairn-mem (revised)

> Persistent memory for coding agents: effective, with no latency or cost penalty, and
> portable to any harness with a shell.
> **Estimate: 4-6 days** (down from 6-9). One milestone is one agent session. Flow:
> understand → red test → implement → measure → tick.

## 1. Review: weak points and what changed

| #   | Weak point in plan v1                                                                                | Change                                                                                                                       |
| --- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 1   | The SLO "p95 < 10 ms" ignored **Python startup**, which is what the agent actually feels             | End-to-end SLO with startup included (M4 revised it to `search` < 350 ms and `save` < 500 ms after measuring the real floor) |
| 2   | `stale` persisted through a `verify` event: it depends on the checkout and diverges between branches | **Calculated when reading**, only for returned results. No event, no state                                                   |
| 3   | Anchor hash differed between Windows and Linux (CRLF), causing false stale flags                     | Hash with **CRLF→LF**. Anchor path is POSIX and relative                                                                     |
| 4   | `hits` through an event on every `get`: reading becomes writing (latency, Git noise)                 | **Out of v0.1** (backlog). L0 uses `kind` priority plus recency                                                              |
| 5   | Raw FTS5 queries **fail** with `-`, `:` and `"` (tested: `oauth-callback` raises an error)           | Required sanitizing: `"t"*` per term, **AND and OR if empty**                                                                |
| 6   | Database out of date after `git pull` (nobody rebuilt it)                                            | JSONL fingerprint `(size, mtime_ns)` → automatic `rebuild`. `user_version` also triggers a rebuild                           |
| 7   | Secret scrubbing in M5 was late: the JSONL may go to Git                                             | **M1**, and by **rejection** (no silent redaction)                                                                           |
| 8   | `MEMORY.md` versioned and regenerated → conflicts and noise                                          | Derived and gitignored. Regenerated on `save/archive`/rebuild, without hooks                                                 |
| 9   | Memory in Git by default in a corporate environment                                                  | **Local-only by default**. `cairn init --share` versions it                                                                  |
| 10  | File lock (`msvcrt`/`fcntl`): complex and not very portable                                          | `O_APPEND` plus **one** `os.write` per event                                                                                 |
| 11  | Own ULID, 6 event types, `scope`/`last_verified`/`hits` columns                                      | 12-hex id plus `ts`. **2 events** (`save`, `archive`). Minimal schema                                                        |
| 12  | BM25 × boosts, lexical dedupe, decay, promotion, LLM `--propose`                                     | Only `bm25()` with column weights. The rest goes to the **backlog**                                                          |
| 13  | Passive capture through a git hook: noise that lowers precision                                      | Out. An explicit rule for **what to save and what not** in `docs/AGENT_SNIPPET.md`                                           |
| 14  | Hand-written MCP with a global scope: cost and risk without proven need                              | **Backlog**. The CLI covers any harness with a shell                                                                         |
| 15  | Windows: `export.sh` needs bash, cp1252 encoding, no `init` and no project root                      | Cross-platform export (standard library). Forced UTF-8 plus a test. `cairn init`. Search `.cairn/` upward                    |
| 16  | A/B of 10-20 tasks: noisy and expensive                                                              | **Golden set** for retrieval (no LLM, in CI) plus a small **paired** A/B                                                     |
| 17  | `get` by long ID (ULID) is error prone for an agent                                                  | Short 12-hex ID                                                                                                              |

## 2. Measurable goals (SLOs)

| Metric                                                   | Target                                                |
| -------------------------------------------------------- | ----------------------------------------------------- |
| `cairn search` end-to-end (Python startup included), p95 | **< 350 ms** idle, 10k (previously 150 ms; see below) |
| `cairn save` end-to-end (L0 render included), p95        | **< 500 ms** idle, 10k (previously 200 ms)            |
| Internal `search` query (10k records)                    | **< 10 ms**                                           |
| In-process MCP tool call (10k records)                   | **< 50 ms**                                           |
| L0 (`MEMORY.md`)                                         | **≤ 3000 characters** (about 900 tokens)              |
| Precision@3 on the golden set                            | **≥ 0.8**                                             |
| Rebuild with 10k events                                  | measure (measured: 1.3 s idle)                        |
| Dependencies / LLM calls                                 | **0 / 0**                                             |

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
- [x] Optional: a Claude Code `Stop` hook that reminds the agent to save (only if we
  measure that the agent does not save) — measured 2026-11-10: 70 memories and 29 recaps in
  this repo, so the agent does save. No hook

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
  [PyPI](https://pypi.org/project/cairn-mem/0.1.0/)). `pip index versions cairn-mem` → 0.1.0.
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

| Round | Improvement                                                                                                                                                                                                                                          | Release               | Evidence                                                                                       |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | ---------------------------------------------------------------------------------------------- |
| S1    | L0 shares the budget across kinds (round-robin)                                                                                                                                                                                                      | 0.3.0                 | [`docs/features/l0-fair-share.md`](docs/features/l0-fair-share.md)                             |
| S2    | `topic_key` visible in the L0 and `search`. FTS indexes `topic_key` and `anchor_path`                                                                                                                                                                | 0.4.0                 | [`docs/features/topic-visibility.md`](docs/features/topic-visibility.md)                       |
| S3    | Cross-scope `search` (project plus personal) and the project session in `context`                                                                                                                                                                    | 0.5.0                 | [`docs/features/transversal-search.md`](docs/features/transversal-search.md)                   |
| S4    | `archive` over MCP and reading older sessions                                                                                                                                                                                                        | 0.6.0                 | [`docs/features/mcp-archive-session-history.md`](docs/features/mcp-archive-session-history.md) |
| S5    | Durability and security: torn tail, same-size replacement, prefixed tokens, validated `id`/`topic`                                                                                                                                                   | 0.7.0                 | [`docs/features/s5-durabilidad-seguridad.md`](docs/features/s5-durabilidad-seguridad.md)       |
| S6    | Honest retrieval benchmark (Hit@3/R@5/MRR/abstention, grep baseline)                                                                                                                                                                                 | — (no runtime change) | [`docs/features/s6-benchmark-retrieval.md`](docs/features/s6-benchmark-retrieval.md)           |
| S6.1  | Query-side plural stem and stopwords; two-root quorum measured and rejected                                                                                                                                                                          | 0.8.0                 | [`docs/features/query-stemming-stopwords.md`](docs/features/query-stemming-stopwords.md)       |
| S7    | Incremental sync: apply only the JSONL tail, guarded by the offset and the prefix sha1                                                                                                                                                               | 0.9.0                 | [`docs/features/s7-incremental-sync.md`](docs/features/s7-incremental-sync.md)                 |
| S7.1  | Certification re-stat: a prefix replaced during the sha1 forces a rebuild                                                                                                                                                                            | 0.9.1                 | [`docs/DECISIONS.md`](docs/DECISIONS.md)                                                       |
| S9    | Audit fixes: one `_session_root`, anchor hash cache, anchor size cap, tail read for `context`, `search --personal` without side effects, `.MEMORY.md.*` ignored                                                                                      | 0.9.1                 | `docs/DECISIONS.md`                                                                            |
| S9.1  | Audit fixes, integrity: apply a JSONL tail without `\n`, torn-tail tolerance by the missing `\n`, `parse_event` with file and line, `Sessions.last` accumulates the window backwards, `MAX_FRAGMENT` 1 MiB, LF `.gitignore`, MCP `save` accepts `id` | 0.9.2                 | `docs/DECISIONS.md`                                                                            |
| S10   | `cairn doctor`: Python/SQLite+FTS5, store root, `events.jsonl`/`sessions.jsonl` line validity, DB sync, L0 budget, stale anchors, `.gitignore` entries and duplicate `cairn` installs. Upgrade docs (no self-update command)                         | 0.10.0                | `docs/features/s10-doctor.md`                                                                  |
| S10.1 | `sessions.jsonl`: a line that is valid JSON but not an object fails with `sessions.jsonl línea N`; torn-tail tolerance requires the missing `\n`                                                                                                     | 0.10.0                | `docs/DECISIONS.md`                                                                            |
| S11   | Sessions: one ordering for `last` and `all`, `id` validated; `context` keeps the head and the tail of long recaps                                                                                                                                    | 0.11.0                | `tests/test_sessions.py`, `docs/DECISIONS.md`                                                  |
| S12   | CLI/MCP symmetry: `search --project`, `--personal` on `rebuild/render/check`, `archive` across both scopes                                                                                                                                           | 0.12.0                | [`docs/features/s12-cli-mcp-symmetry.md`](docs/features/s12-cli-mcp-symmetry.md)               |
| S13   | Secret filter v2: `Bearer`, `ASIA`, `xox[baprs]-`, `sk_live_`/`rk_live_`, `npm_`                                                                                                                                                                     | 0.11.0                | `tests/test_store.py` (reject + prose cases)                                                   |
| S14   | Bench hygiene: clean `mkdtemp` dirs, exit 1 when an SLO fails                                                                                                                                                                                        | — (bench-only)        | [`docs/features/s14-bench-hygiene.md`](docs/features/s14-bench-hygiene.md)                       |
| S15   | MCP annotations (`readOnlyHint`, `idempotentHint`, `destructiveHint`), `cairn mcp --read-only` (solo las 5 tools de lectura) y `search --kind/--topic/--stale` con el flag `partial` del fallback OR                                                                                                                              | 0.14.0                | [`docs/features/s15-mcp-annotations-read-only.md`](docs/features/s15-mcp-annotations-read-only.md) |
| S16   | Agent setup: `cairn setup claude-code\|opencode [--dir]` escribe la config MCP y el snippet entre marcas; merge sin pisar el resto del fichero; JSONC con comentarios se rechaza con el bloque a pegar                                      | 0.15.0   | [`docs/features/s16-setup-harness.md`](docs/features/s16-setup-harness.md)                     |
| S16.1 | `cairn export [--personal] [--sessions N] [--out PATH]`: memoria activa a Markdown por kind, sin marcas de stale y con salida determinista                                                                                                          | 0.15.0   | [`docs/features/s16-setup-harness.md`](docs/features/s16-setup-harness.md)                     |
| S17   | Trusted Publishing: `.github/workflows/publish.yml` (OIDC, attestations PEP 740); PyPI deja de mostrar "No provenance"                                                                                                                               | — (release infra)     | [`docs/features/s17-trusted-publishing.md`](docs/features/s17-trusted-publishing.md)            |
| S18   | Procedencia opcional de la memoria: `source` en `save` (CLI/MCP), validado e indexado. Sin estado "sin revisar": el PR sobre `events.jsonl` ya es la revisión humana                                                                                 | 0.13.0                | [`docs/features/s18-source-provenance.md`](docs/features/s18-source-provenance.md)             |
| S19   | Hardening del borde: `parse_event` acota y controla todo el metadato (`why` ≤ 2000 tolerando el `\n` histórico, topic/anchor caps, `title` sin controles); `Sessions` solo sirve registros completos (id 12 hex + summary)                              | 0.14.0                | `tests/test_store.py`, `tests/test_sessions.py`, `docs/DECISIONS.md`                            |
| S20   | Auditoría externa: secretos v3 por forma del valor y formatos (Oracle/SAS/Fernet/Azure/sk-/Slack), rechazo de inyección con cabecera en el L0, dedupe no bloqueante (aviso a 0,3-0,9, bloqueo a 0,9), `pin`/`unpin` solo CLI, `purge`, `topics`, `doctor` reescanea secretos y L0/MCP en inglés | 0.16.0                | [`docs/features/s20-security-dedupe-pin.md`](docs/features/s20-security-dedupe-pin.md)         |
| S21   | A/B de escritura (`bench/ab_write.py`: ¿el agente guarda el gotcha que acaba de descubrir? con controles stale, envenenado y 100 distractores; criterios escritos antes de medir), `setup` sin bloque duplicado cuando el fichero importa `@AGENTS.md`, `CAIRN_LANG` (inglés por defecto en CLI/`doctor`/`setup`, `es` opt-in; el núcleo y el MCP siempre en inglés) | 0.17.0 | [`docs/features/s21-write-ab-lang-setup.md`](docs/features/s21-write-ab-lang-setup.md) |
| S22   | `keywords` indexado en FTS (`SCHEMA_VERSION = 6`), `cairn history <topic>` y lock de fichero entre procesos (el test de 8 procesos midió la pérdida de eventos) | 0.17.0 | [`docs/features/s22-retrieval-fields.md`](docs/features/s22-retrieval-fields.md) |
| S23   | Snippet imperativo (antídoto a "write-side 2/30"): obligación con momento, el porqué del usuario va en `--why`; medido 17/30 frente a 2/30 al -17 % de tokens, criterio primario incumplido (LB 0,392 < 0,5); dos defectos del banco de escritura corregidos | sin release | [`docs/AB_RESULTS.md`](docs/AB_RESULTS.md) |
| S24   | El lock entre procesos pasa a `<fichero>.lock`: bloquear byte 0 de `events.jsonl` impedía leerlo desde otro proceso en Windows y el `rebuild` moría con `PermissionError` (2 de 5 corridas del test concurrente) | sin release | `tests/test_jsonl.py`, `docs/DECISIONS.md` |
| S25   | `purge` toma el lock del append (`_LOCK` + `<fichero>.lock`) alrededor de la lectura y del replace: un `save` concurrente entre ambos caía en el fichero viejo y se perdía | sin release | `tests/test_s20.py`, `docs/DECISIONS.md` |
| S26   | `events.jsonl.bak` entra en las entradas gestionadas del `.gitignore` (y en `doctor`) | `purge` escribe la copia con el secreto dentro; en `--share` un `git add .` la commiteaba (medido: `git status` mostraba `?? .cairn/events.jsonl.bak`) | sin release | `tests/test_s20.py`, `tests/test_cli.py` |
| S27   | Ronda 3 del A/B de escritura: el snippet más un `Stop` hook que empuja una vez por sesión. Medido 30/30 (IC95 0,886-1,000) contra `imperative` 20/30 en la misma corrida, 1,11x tokens; el riesgo "el agente no guarda" queda cerrado por medición | sin release | [`bench/ab_write_protocol.md`](bench/ab_write_protocol.md) §"Round 3 (S27)", [`docs/AB_RESULTS.md`](docs/AB_RESULTS.md) |
| S28   | `setup opencode` instala el hook `Stop` medido desde un asset del paquete; el instalador y el banco comparten un solo fichero (`setup.install_hook`), así que lo medido y lo instalado no pueden divergir. Claude Code se queda abierto: su `Stop` es otro mecanismo sin brazo | sin release | `tests/test_setup.py`, `docs/DECISIONS.md` |

**0.8.0 release:** 2026-11-09 on PyPI (wheel and sdist) and tag `v0.8.0`. Verified with a
clean install (`init`, `save`, `search`, `session`).

**0.9.0 release:** 2026-11-10 on PyPI (wheel and sdist) and tag `v0.9.0`. Verified with a
clean install from the public index (`init`, `save`, `search`).

**0.9.1 release:** 2026-11-10 on PyPI (wheel and sdist) and tag `v0.9.1`. S7.1, S9 and the
per-render anchor cache. Every gate in `AGENTS.md` is measured in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

**0.9.2 release:** 2026-11-11 on PyPI (wheel and sdist) and tag `v0.9.2`. S9.1 closes the
five integrity bugs from the audit. Verified with a clean install from the public index
(`init`, `save`, `search`, version 0.9.2).

**0.10.0 release:** 2026-11-12 on PyPI (wheel and sdist) and tag `v0.10.0`. S10 adds
`cairn doctor`; S10.1 validates `sessions.jsonl` events. Verified with a clean install from
the public index (`init`, `save`, `doctor` exit 0, version 0.10.0).

**0.11.0 release:** 2026-11-12 on PyPI (wheel 35.428 B, sdist 58.043 B) and tag `v0.11.0`.
S11 unifies the session order and keeps the tail of a long recap; S13 widens the secret
filter. Verified with a clean install from the public index in an empty venv (`init`,
`save`, `search`, `doctor` exit 0, version 0.11.0).

**0.12.0 release:** 2026-11-16 on PyPI (wheel 36.175 B, sdist 60.986 B) and tag `v0.12.0`.
S12 gives the CLI the scopes the MCP tools already had (`search --project`, `--personal`
on `rebuild/render/check`, `archive` across both scopes). Verified with a clean install
from the public index in an empty venv (`init`, `save`, `search`, `doctor` exit 0,
version 0.12.0).

**0.13.0 release:** 2026-11-17 on PyPI and tag `v0.13.0`. First release published from
GitHub Actions with Trusted Publishing (S17: `publish.yml`, OIDC, PEP 740 attestations;
no PyPI credential in the repo). Contents: S14 bench hygiene, S15 partial (MCP
annotations and `cairn mcp --read-only`) and S18 (optional `source` provenance,
`SCHEMA_VERSION = 4`). Verified with a clean install from the public index in an empty
venv (`init`, `save`, `search`, `doctor` exit 0, version 0.13.0) and the PyPI page
showing provenance.

**0.14.0 release:** 2026-11-17 on PyPI and tag `v0.14.0`. Contents: the S15 remainder
(`search --kind/--topic/--stale` in CLI and MCP, with `partial` as an output field of the
OR fallback) and S19 (the parse edge caps and controls every metadata field; `Sessions`
fails on a corrupt record outside a torn tail). No schema change. Verified with a clean
install from the public index in an empty venv (`init`, `save`, `search`, `doctor` exit 0,
version 0.14.0).

**0.15.0 release:** 2026-11-18 on PyPI and tag `v0.15.0`. Contents: S16 (`cairn setup
claude-code|opencode [--dir]` writes the harness MCP config and the rules snippet between
markers, idempotent, merge-safe and refusing a commented JSONC config) and S16.1
(`cairn export` dumps active memory to Markdown). No schema change. Verified with a clean
install from the public index in an empty venv (`init`, `save`, `search`, `doctor` exit 0,
`setup` and `export` included, version 0.15.0).

**0.15.1 release:** 2026-11-18 on PyPI and tag `v0.15.1`. Patch for two S16 defects found
in the post-release review: a config file that parses but is not a JSON object (`[]`, a
scalar) raised `AttributeError` instead of failing as a user error, and the rules snippet
was written as LF into a CRLF instructions file. No API or schema change. Verified with a
clean install from the public index in an empty venv (`setup` with a config that is not an
object exits 1, CRLF file normalized, version 0.15.1).

**0.16.0 release:** 2026-11-18 on PyPI and tag `v0.16.0`. Contents: S20 (secret detector
v3 keyed by value shape and format, injection rejection plus the L0 header, non-blocking
dedupe, human `pin`/`unpin`, `purge`, `topics`, `doctor` secret scan, agent-facing English
L0/MCP and the paraphrase baseline). `SCHEMA_VERSION = 5` (`pinned` column; older JSONL
replays with 0 and the schema mismatch rebuilds on open). Verified with a clean install
from the public index in an empty venv (`init`, `save`, `search`, `pin`, `topics`, `purge`,
`doctor` exit 0, version 0.16.0).

**0.17.0 release:** 2026-11-20 on PyPI and tag `v0.17.0`, published from GitHub Actions
with Trusted Publishing. Contents: S21 (write-side A/B with pre-registered criteria,
`setup` de-dup through `@AGENTS.md`, `CAIRN_LANG`) and S22 (`keywords` indexed in FTS with
`SCHEMA_VERSION = 6`, `cairn history <topic>` and the cross-process JSONL lock). The schema
goes v5 to v6: the derived DB rebuilds on open and older JSONL replays with `keywords`
NULL. Verified with a clean install from the public index in an empty venv (`init`, `save`,
`search` by a keyword, `history`, `doctor` exit 0, version 0.17.0).

## 4.1 Pending rounds (2026-11-18 audit)

S21 and S22 shipped in 0.17.0. Each one started only after the previous was measured; keep
the one-round-per-release rule and add its row to the §4 table when it ships.

### S21: write-side A/B, setup de-dup, languages (P1)

- [x] **A/B v2, write side.** `bench/ab_write.py`: one session per run on a toy repo where
  the agent moves `/health`'s `time` to epoch seconds because the data team reads it from
  another timezone, so the reason exists only in the request, not in the code. The run only
  counts when `events.jsonl` gained a **new** `save` whose text matches the topic
  (`epoch|utc|tz|timezone|iso|timestamp`). Arms:
  `plain` (control), `empty`, `stale`, `poison` and `distractors` (100 fillers). Criteria
  pre-registered in [`bench/ab_write_protocol.md`](bench/ab_write_protocol.md) (n ≥ 30 per
  arm, Wilson 95%, the `empty` lower bound ≥ 0.5 and no overlap with `plain`, controls
  within 0.20 of `empty`). **Measured 2026-11-20** (`--arms empty,plain`, n = 30): `empty`
  2/30 (IC95 0.018-0.213), `plain` 0/30 (0.000-0.114), 0 non-zero exits. Criterion 1 fails
  (lower bound 0.5 and the intervals overlap), so the three control arms were not run and
  the risk "the agent does not save memories" stays open. Numbers in
  [`docs/AB_RESULTS.md`](docs/AB_RESULTS.md). The harness is covered by
  `tests/test_ab_write.py` (detection, Wilson and cleanup with a fake run). Smoke on
  2026-11-19 with the final scenario: `plain` 0/1, `empty` 0/1 (a probe confirmed the
  model reads the snippet, so the zero is the model not saving).
- [x] **`setup` without duplication.** When `CLAUDE.md` imports `@AGENTS.md`, the snippet
  block is not written there, and a block left by an older setup is removed.
- [x] **`CAIRN_LANG`.** English by default for the human-facing messages (CLI, `doctor`,
  `setup`), `CAIRN_LANG=es` opt-in through `i18n.t(en, es)`. The agent-facing surface (L0,
  MCP) and the library edge (`store`, `sessions`, `anchor`, `paths`, `jsonl`, `mcp`) are
  English only, so a tool error cannot change language with the environment.

### S22: retrieval fields and concurrency (P2)

- [x] **`--keywords` indexed in FTS** (`SCHEMA_VERSION = 6`) for the queries whose terms are
  not in the memory ("dónde guardo las contraseñas" → "secretos", "nombrar objetos de BD" →
  "vistas en mayúsculas"). Gate: the hard paraphrase set (`bench/paraphrase.jsonl`, baseline
  léxico 8/8, flexión 8/8, paráfrasis 9/10) must not regress and should improve P@3.
  **Measured 2026-11-20:** paráfrasis 10/10, overall Hit@3 0.96 → 1.00, MRR 0.94 → 0.98,
  léxico y flexión 1.00; `bench/retrieval.jsonl` sin cambio (0.97/1.00/0.96). Sin keywords
  las métricas son idénticas al baseline. `tests/test_s22.py` fija el gate en CI.
- [x] **`cairn history <topic>`**: the superseded rows of a topic from the JSONL (the
  history already exists; no graph). Implemented over the derived `mem` rows (they keep
  `superseded`/`archived`); `--json` adds `scope`, order is `(ts, rowid)` and both scopes
  are merged chronologically.
- [x] **Windows multiprocess test**: 8 processes appending in CI `windows-latest`;
  `jsonl._LOCK` is only in-process, so `_repair_tail` could truncate another process's
  half-written line. **Measured 2026-11-20:** before the fix, 8 × 25 appends left 190, 195
  and 197 valid lines of 200 (lost ids and empty lines). Fixed with a file lock
  (`msvcrt.locking` byte 0 on Windows, `fcntl.flock` on POSIX) around repair + write; the
  test seeds a torn tail and asserts 200 valid lines and a clean rebuild (5/5 repeat runs).

### S23: the imperative snippet (write side)

- [x] **Round 2 of the write-side A/B.** `--arms imperative --reps 30`: the save rule
  becomes an obligation with a moment and says the user's reason goes into `--why`.
  **Measured 2026-11-20:** 17/30 (IC95 0.392-0.726) against 2/30 (0.018-0.213), 18,188
  tokens against 21,826, 30/30 `exit == 0`. Criterion 1 **fails** (LB 0.392 < 0.5) and is
  reported as such; criterion 2 was not verifiable because the rows did not carry the saved
  text. Numbers in [`docs/AB_RESULTS.md`](docs/AB_RESULTS.md).
- [x] **Shipped the better text anyway,** on the measured axes (8.5x saves, -17 % tokens):
  `SNIPPET` in `setup.py` and the block in `docs/AGENT_SNIPPET.md`, pinned equal by
  `tests/test_ab_write.py` and `tests/test_setup.py`.
- [x] **Two bench defects:** `ab._snippet()` sliced the doc by line number (round 1's
  control carried two prose lines and a stray fence) and the `--json` rows lost the saved
  text (`saves` now carries kind/title/body/why, so the next round can be audited).
- [x] Next lever: a `Stop` hook that asks for the decisions when the session goes idle. Its
  criteria were pre-registered in
  [`bench/ab_write_protocol.md`](bench/ab_write_protocol.md) §"Round 3 (S27)" (2026-11-21,
  before any run): arm `stop` = the shipped snippet plus one nudge per session.
  **Measured 2026-11-21:** 30/30 (IC95 0.886-1.000) against `imperative` 20/30
  (0.488-0.808) in the same interleaved run, 16,329 tokens against 14,673 (1.11x), 7
  sessions nudged once and all 7 saved after the nudge, 60/60 exits 0. Criteria 1-6 pass,
  so the risk row closes and the hook ships with the snippet (S28, below).

### S28: the Stop hook install path

- [x] `cairn setup` writes the hook per harness: an OpenCode plugin from one asset, and for
  Claude Code its own `Stop` hook if the mechanism differs. The hook must filter sessions by
  their project directory (the plugin API is server-wide; an unscoped probe nudged other
  projects, S27) and nudge at most once per session. **Shipped 2026-11-22 for OpenCode only:**
  the asset lives in `src/cairn_mem/assets/stop/index.ts` (package data, in the wheel and the
  sdist) and `setup opencode` writes `.opencode/plugins/cairn-stop/index.ts`. Claude Code's
  `Stop` is a different mechanism (settings file, it blocks the turn) and has no arm in
  `bench/ab_write.py`, which only runs `opencode run`; installing it unmeasured would break
  the rule that a lever ships with a measurement. It stays open with its own arm as the
  condition.
- [x] The install is idempotent and only touches the repo, like the rest of `setup`; the
  shipped text is pinned to the measured one by a test, so the bench artefact cannot drift
  from what users get. **One file, not a copy:** `bench/ab_write.py` now installs the hook
  through `setup.install_hook` (the user path) instead of copying `bench/assets/stop`, and
  `tests/test_setup.py` asserts the installed bytes equal `HOOK_ASSET`.
- [x] Re-run `python bench/ab_write.py --arms imperative,stop --reps 10` against the
  installed hook (not the asset) as a smoke; the 30/30 measurement stands as the result.
  **Measured 2026-11-22:** `imperative` 7/10, `stop` 8/10, 20/20 exits 0, 2 sessions nudged.
  The plugin loads from the installed path and fires once per session; n = 10 is noise for
  the rate, so round 3's 30/30 stays the number. In [`docs/AB_RESULTS.md`](docs/AB_RESULTS.md).

### Minors

- [x] `cairn --version` (nothing printed the version; MCP does it in `serverInfo`).
  `action="version"` on the root parser plus one test in `tests/test_cli.py`.
- [x] Classifiers list 3.10-3.14.
- [x] 0 mypy errors (were 13): `TypedDict` for `HARNESSES`, annotated `Server` caches,
  `dict[str, object]` for the `save` payload, `_split` returns `str | None` and two asserts
  in the importer's dry-run paths, and `sys.platform` instead of `os.name` so mypy prunes
  the `fcntl` branch. `mypy` joins the `dev` extras and CI so the count stays 0.
- Dropped: lazy imports (Windows pays process startup, MCP is the answer; Linux imports
  were 46 ms). Git history email: **not** rewritten; going forward commits use the GitHub
  noreply address.

## 4.2 Audit 2026-11-21: findings

Whole-repo audit (bugs, risk, scale, missing test, speed, lean). Load assumed: one
developer with up to 8 local agent processes sharing the repo and the personal scope, 10k
memories, 20 KB recaps. S25 and S26 are fixed in this round; the rest stay open, most
important first. Moving one into a round needs its test, as always.

| # | Group | Finding | Where | Status |
|---|-------|---------|-------|--------|
| 1 | Must fix | `purge` read and replaced `events.jsonl` outside the cross-process lock: a concurrent `save` was lost (test fails without the fix) | `store.py` `purge` / `_remove_events` | done, S25 |
| 2 | Must fix | `events.jsonl.bak` (the purged secret) was not gitignored: `git add .` committed it | `cli.py` `GITIGNORE`, `doctor.py` | done, S26 |
| 3 | Must fix | `doctor` re-scans secrets in `events.jsonl` but not in `sessions.jsonl` nor `anchor_path` | `doctor.py` `_events`, `_sessions` | done, 2026-11-22 |
| 4 | Must fix | A torn tail cut inside a multi-byte UTF-8 char aborts the whole decode before the torn-tail tolerance | `store.py` `rebuild`, `doctor.py`, `sessions.py` | done, 2026-11-22 |
| 5 | Must fix | `Store.save` raises `TypeError` on a non-string `body` and never validates `anchor_hash`, so a caller can write an event the rebuild rejects | `store.py` `save` | done, 2026-11-22 |
| 6 | Should fix | MCP `archive` does not fall back to the personal scope, unlike CLI `archive` and MCP `get` | `mcp.py` `_archive` | done, 2026-11-22 |
| 7 | Should fix | The MCP internal error message is Spanish (`"error interno"`), breaking the English-only MCP edge | `mcp.py` `serve` | done, 2026-11-22 |
| 8 | Should fix | `GITIGNORE` is duplicated in `cli.py`/`doctor.py` and already drifted (`cairn.db-*` missing); `_date` duplicated in `export.py`; four CLI commands repeat the scope lookup | `cli.py`, `doctor.py`, `export.py` | done, 2026-11-22 |
| 9 | Should fix | `_ignore_sessions` does nothing for the personal scope (it has no `.gitignore`) and MCP `save_session` never calls it | `cli.py`, `mcp.py` | done, 2026-11-22 |
| 10 | Should fix | No test for a corrupt `cairn.db` in `doctor` nor for a torn multi-byte UTF-8 tail | `tests/test_doctor.py`, `tests/test_jsonl.py` | done, 2026-11-22 |
| 11 | Nice to have | `render_l0` rebuilds the joined string for every candidate instead of tracking `used` | `render.py` | done, 2026-11-22 |
| 12 | Nice to have | `_catch_up` runs one `SELECT 1 FROM mem WHERE id = ?` per appended event | `store.py` `_catch_up` | done, 2026-11-22 |

Closed on 2026-11-22 in one batch, with a test per fix (436 → 454 tests): `decode_jsonl`
trims a torn tail before decoding; `save` validates `body`/`anchor_path`/`anchor_hash`
with the `parse_event` contract; `doctor` re-scans secrets in `sessions.jsonl` and
`anchor_path`; `GITIGNORE_ENTRIES` and `ignore_sessions` live in `paths.py` and
`format_ts` in `store.py`; MCP `archive` falls back to the personal scope,
`save_session` writes the personal `.gitignore` and the internal error is English;
`render_l0` tracks `used`; `_catch_up` checks every appended id in one query.

Not checked: `bench/ab.py` and `bench/ab_write.py` against a live `opencode` CLI (model
tokens) and the PyPI trusted-publisher settings in GitHub.

## 5. Backlog (closed with evidence, 2026-11-16)

Every item was measured on 2026-11-10 and 2026-11-16 (numbers in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md), rationale in
[`docs/features/backlog-triggers.md`](docs/features/backlog-triggers.md)). Nothing is
pending a measurement any more: each item is closed and carries the condition that
reopens it.

- `hits` in a local, non-versioned table plus a ranking boost. **Closed:** golden
  Precision@3 30/30, honest retrieval Hit@3 0.97, A/B 16/16. Reopen if a real corpus puts
  the right memory outside the top 3 while the query terms match it.
- `compact`/decay. **Closed:** 52 → 10,052 memories without relation keeps Hit@3 0.97 and
  Recall@5 1.00 (MRR 0.96 → 0.94), and the L0 already truncates at 3000 characters.
  Reopen only with real near-duplicate memories that drop Precision@3 below 0.8; synthetic
  duplicates would measure the fixture.
- `sqlite-vec`. **Closed:** paraphrase Hit@3 0.90 ≥ 0.8 at 52 and 10,052 memories.
  Reopen if paraphrase Hit@3 falls below 0.8 on the dataset or a real corpus.
- Passive capture through a git hook. **Closed:** the retrieval A/B had the agent read the
  memory without a hook (16/16). Reopen if sessions show the agent not saving and the
  snippet rule is not enough. **Trigger met, measured (2026-11-20):** the write-side A/B
  scored `empty` 2/30, so the agent does not save after learning. S23 measured the wording
  lever (17/30, criterion LB 0.392 < 0.5) and shipped it; the `Stop` hook closed the gap on
  2026-11-21 (30/30 against `imperative` 20/30, same run).
- `anchor_cache` table in `cairn.db`. **Closed after its trigger fired:** 200 anchors of
  256 KiB (50 MB) added 81 ms to the p50 of `save`. The safe part is applied instead
  (`render_l0` hashes the candidate anchors in 8 threads: 81 → 58 ms), because reusing a
  hash across commands by `(size, mtime_ns)` is exactly what the stale guarantee forbids
  (NTFS updates `mtime` late) and a content-verified identity means reading the file again.
  Reopen only with a stdlib file identity that changes with the content without reading
  it, or if a real repo exceeds `save` p95 500 ms at 10k.

## 6. Risks (the ones left)

| Risk                                                              | Mitigation                                                                                                   |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| The agent does not save memories                                  | Clear rules in the snippet plus the `Stop` hook. **Closed by measurement 2026-11-21:** with the hook 30/30 (IC95 0.886-1.000) against 20/30 (0.488-0.808) for the text alone, same run, 1.11x tokens; the install path ships in S28 |
| The agent saves junk                                              | A "do NOT save..." rule, a 500-character limit and `topic_key` to replace old entries                        |
| Stale due to a whole-file anchor (false positives on large files) | It only warns (`⚠ revisar`), it does not hide. Measure the rate in the A/B. Anchor to the most specific file |
| Windows startup latency (antivirus, pipx shim)                    | Measure end-to-end in M4. Minimal imports                                                                    |
| Out-of-date memory after `git pull`                               | JSONL fingerprint plus automatic rebuild                                                                     |
| Secrets                                                           | Rejection on write plus local-only by default                                                                |
| FTS5 missing in some Python build                                 | Check at startup and fail with a clear message                                                               |

## 7. Startup prompt for the agent

```text
Read AGENTS.md, PLAN.md and docs/DESIGN.md. Implement ONLY M1 with TDD
(tests/test_store.py is already red). Standard library only. Show the real pytest
output, tick the M1 checklist in PLAN.md and do not move on to M2.
```
