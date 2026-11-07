# S4: `archive` over MCP and older session recaps

**Goal:** full CLI and MCP parity. The agent can retire a memory without leaving the
harness, and it can read older sessions without overwriting the current context
(`context` only returns the last one, and until now there was no way to read the one
before).

## Scope

- Three new tools in `mcp.py`, with no changes to `store.py`, `sessions.py` or the CLI:
  - `archive` (requires `id`, `scope` `project|personal`): archives the memory like
    `cairn archive`, and fails if it does not exist (the store does not validate).
  - `session_list` (optional `limit` 1-50, default 20; `scope`): lists recent sessions as
    JSON with `{id, ts, preview}` (summary collapsed to the first 200 characters).
  - `session_get` (requires `id`, `scope`): returns the full record as JSON, and fails if
    it does not exist.
- Names avoid `session` / `sessions` alone: OpenCode already filtered a tool because of a
  name collision (0.2.2).
- Re-archiving an archived memory rewrites the archive event (the store only requires the
  memory to exist), just like the CLI. It is not an error, but it does write one event per
  call.
- No `rebuild`, `render` or `check` tool: they are maintenance, not part of the agent flow.

Out of scope: the CLI (it already has everything), the L0, ranking and the importer.

## Acceptance criteria

1. `tools/list` shows `save, search, get, context, save_session, archive, session_list,
   session_get`.
2. MCP `archive` archives in the project and in the personal scope. An unknown id returns
   a structured error (`isError`).
3. `session_list` returns sessions newest first and respects `limit`. `session_get`
   returns the full recap. An unknown id returns an error.
4. `scope` controls the root: `personal` does not mix project sessions.
5. `limit` is clamped to 1-50, and a non-numeric `limit` returns a structured error.
6. Suite and `ruff` pass. One `bench_mcp` run shows no regression in the measured tools.

## Evidence (2026-11-05)

- `pytest -q`: **153 passed** (7 new tests in `tests/test_mcp.py`; the `tools/list` test
  was rewritten for the full set). 7 were red before the implementation.
- `ruff check src tests bench`: clean.
- `bench/bench_mcp.py --reps 20` with 10k: search p95 5.9 ms / save 23.0 ms / context
  14.3 ms (**SLO p95 < 50 ms: OK**).
- `bench/bench_cli.py --reps 20` (10k): the first pass was noisy (search p95 384-414 ms,
  save 241-366 ms). A consecutive paired pass from the v0.5.0 baseline to the branch:
  v0.5.0 search p95 340.6 / save 364.0; branch search p95 321.9 / save 339.2 ms.
  **SLO search < 350, save < 500: OK in both**. The noise came from the machine, not the
  code (the `search` CLI is not touched; internal 2.8 vs 3.1 ms).
- Real MCP cycle: `save` → `archive` → `search` no longer returns it and `dump` marks it
  `archived`. `save_session` twice → `session_list` returns the newest first with a
  preview, and `session_get` returns the full recap. `scope=personal` does not mix
  sessions.
- Development erratum: the first version of `_session_root` evaluated `if _scope(...)`,
  which is truthy for `"project"`, so it always read the personal scope. The scope test
  caught it.
