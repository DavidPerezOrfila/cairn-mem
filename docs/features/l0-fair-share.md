# S1: the L0 shares its budget across kinds

**Goal:** a kind with many entries should not push the others out of the L0. The budget
stays at 3,000 characters.

## Scope

- `Store.active_ordered` returns active memories in round-robin across kinds: one
  `convention`, one `decision`, one `gotcha`, one `fact`, then repeat. Inside each kind,
  newest `ts` first, with `id` as the tie-breaker.
- Partial index `(kind, ts DESC, id) WHERE status = 'active'`, so each round reads 200 rows
  instead of scanning the table four times.
- `render.py`, the line format, `EXCERPT`, the 3,000-character limit and the `stale`
  calculation do not change.

Out of scope: configurable percentage quotas, a new kind, a `SCHEMA_VERSION` change (the
index is created with `IF NOT EXISTS` when the store opens).

## Acceptance criteria

1. With 4 kinds present and 30 newer decisions, the L0 includes all four kinds.
2. The L0 is ≤ 3,000 characters and byte-identical between two runs.
3. MCP `context` p95 < 50 ms with 10k.
4. Suite and ruff pass.

## Evidence (2026-11-04, real repo and 10k benchmark)

| Metric | Before | After |
|---|---|---|
| Repository L0 | 2,919 chars, 15 lines, **15 `decision`** | 2,991 chars, 15 lines, **5 `decision` + 5 `gotcha` + 5 `fact`** |
| `active_ordered` (10k) | 13.3 ms p50 | 8.2 ms p50 |
| MCP `context` (10k) | 18.4 ms p95 (docs) | 23.0 ms p95 (`bench_mcp --reps 20`) |
| `cairn render` end-to-end | 315-376 ms | 288-393 ms |

- `pytest -q`: 128 passed. `ruff check src tests bench`: clean.
- `python bench/bench_mcp.py --reps 20`: search 10.6 / save 27.6 / context 23.0 ms p95,
  so it meets the SLO (< 50 ms).
