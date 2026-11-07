# S3: cross-scope `search` and the project session in `context`

**Goal:** one search should find project memory and personal memory at the same time, so
the agent does not have to guess where the answer lives. Also, `context` should load the
project session, not a recap from another repo.

## Scope

- `search` (CLI and MCP) queries the project **and** the personal scope, then interleaves
  results by ranking position (BM25 scores from different databases are not comparable).
  Each result carries `scope` (`project|personal`). In text, the personal scope is marked
  `[personal]`.
- `--personal` / `scope=personal` is still the explicit filter: personal only. MCP also
  accepts `scope=project`; without `scope`, it uses `all`.
- If `~/.cairn` does not exist, the project works as before and the directory is not
  created. If there is no project but `~/.cairn` exists, the search returns personal
  memory. With neither, it fails with `cairn init`. `--personal` does create `~/.cairn`,
  like `save`.
- `context` returns the L0 followed by the last recap **from the project**.

Out of scope: a new ranking, changes to `save`, `get` or `archive`, the L0, the importer
and sessions (recaps are still saved per scope).

## Acceptance criteria

1. With one project memory and one personal memory that match the query, `search` without
   a filter returns both, each with its `scope`.
2. `search --personal` and `scope=personal` return only the personal one. `scope=project`
   returns only the project one.
3. Without `~/.cairn`, `search` works as before and does not create the directory. Without
   a project `.cairn/` but with a personal scope, it returns personal memory. With
   neither, it fails with `cairn init`.
4. The limit applies to the combined result. The split is round-robin starting with the
   project, and it never leaves out a scope with matches when they fit.
5. `context` includes the last project recap and ignores a newer personal one.
   `MEMORY.md` does not change.
6. Suite and `ruff` pass. Precision@3 is 30/30. MCP `search` p95 < 50 ms with 10k.

## Evidence (2026-11-04)

- `pytest -q`: **146 passed** (8 new tests: store, CLI and MCP; 2 existing tests were
  rewritten because they pinned the previous behavior).
- `ruff check src tests bench`: clean.
- Precision@3: 30/30 (`pytest -q tests/test_golden.py`).
- `python bench/bench_cli.py --reps 40` with the real personal scope (18 memories):
  10k → search p95 309.3 ms, save p95 329.6 ms, internal 4.5 ms.
  `bench_mcp --reps 40`: search 6.6 / save 17.9 / context 12.4 ms p95. One run with the
  agent loading the CPU gave 13.5 / 29.9 / 31.0 ms p95, still under 50 ms.
- Cost of the second database, measured separately (20 repetitions): MCP `search` p95
  7.4 ms with a real `~/.cairn` against 4.7 ms with an empty `CAIRN_HOME`.
- `cairn search "mcp"` on the real repo (trimmed):
  ```text
  24e4a65ea4b2  decision  [cairn/opencode-mcp]  MCP validado en OpenCode — …
  6edbfe4f2ae1  decision  [open-pacman/config/ecc-opencode]  [personal]  MCP de Engram…
  8e7a50e7df08  decision  [cairn/mcp]  MCP por stdio con 4 tools — …
  3b6536818717  gotcha  [06-open-daycare/opencode/engram-mcp-spawn]  [personal]  Fixed…
  c4db88e5939c  decision  [harness/mcp-global]  OpenCode queda solo con el MCP de cairn
  ```
- `context` through the real `cairn mcp`: it injects the L0 and the project session (the
  S2 recap), not the personal session.
- Repository L0: 2,905 characters (unchanged; this round does not touch `MEMORY.md`).
- `~/.cairn` is not created if it does not exist:
  `test_search_does_not_create_personal_dir` (CLI) and the MCP equivalent.
