# S12: CLI/MCP symmetry

## Goal

The CLI reaches the same scopes the MCP tools already reach, without a flag the user has
to remember depending on the command.

## Scope

- `search --project` restricts the search to the project (mutually exclusive with
  `--personal`). Default stays cross-scope.
- `rebuild`, `render` and `check` accept `--personal`.
- `archive <id>` looks in the project and then in the personal scope, like `get`; the
  `--personal` flag disappears because the id decides the store.
- Out of scope: new MCP tools or arguments (MCP already has `scope` in `save`, `search`,
  `archive` and the session tools), and a `--project` flag on `get` (a 12-hex id is unique
  per store and `get` already checks both).

## Acceptance

- `pytest -q`: `search --project` returns only project rows; `--project` without a store
  fails with the `cairn init` message and does not create the personal scope; `--project`
  and `--personal` together exit 2; `render/check/rebuild --personal` read and write the
  personal store (stale anchor included); `archive` retires a personal id without the
  flag; `archive` with no store at all fails like `get`.
- Full suite green (251 tests) and `ruff check src tests bench` clean.
- README, `docs/DESIGN.md` and `PLAN.md` describe the flags; `docs/DECISIONS.md` records
  why `archive` drops its flag.

## Evidence

```text
python -m pytest -q
251 passed in 28.76s

ruff check src tests bench --output-format=concise
All checks passed!
```
