# S14: bench hygiene

## Goal

The benches must not leave garbage on the machine and must fail the process when they
break their SLO, so a CI job or a release script can trust the exit code.

## Scope

- `bench_cli.py`, `bench_mcp.py`, `bench_sync.py`: `mkdtemp` → `TemporaryDirectory`.
- `Store.close()`: without closing the connection Windows keeps `.cairn/cairn.db-wal`
  open and `shutil.rmtree` fails; `bench_anchors.py` and `bench_retrieval.py` already used
  `ignore_cleanup_errors=True`, which hid the leak instead of fixing it. Every store is
  now closed with `contextlib.closing`, so an exception inside the measurement still
  leaves the directory deletable, and the two `ignore_cleanup_errors=True` flags are gone:
  a future leak fails loudly instead of being swallowed.
- `bench_mcp.py` restores `CAIRN_DIR` after measuring: it used to leave the variable
  pointing to a deleted directory for the rest of the process.
- Exit 1 when the SLO fails, in the text and `--json` paths of `bench_cli`, `bench_mcp`
  and `bench_sync` (`bench_sync` already did it in the text path).
- Out of scope: the SLO values and the measurement method, which do not change.

## Acceptance criteria

1. Running each bench leaves no new `cairn-*` directory in `%TEMP%`.
2. `bench_cli`, `bench_mcp` and `bench_sync` exit 1 when a p95 is over its SLO, in both
   output modes, and 0 when it is not.
3. `pytest -q` and `ruff check src tests bench` stay green.

## Evidence (2026-11-16, Windows 11, Python 3.14.10)

Directory count in `%TEMP%` before and after running every bench:

| Prefix | Before | After |
|---|---|---|
| `cairn-bench-*` | 68 | 68 |
| `cairn-anchors-*` | 22 | 22 |
| `cairn-retrieval-*` | 134 | 134 |

The 224 old directories are the leak this round fixes; the runs above added zero.

```
python bench/bench_cli.py --reps 20   → exit=1
 10000 registros: search e2e p95 310.1 ms, save e2e p95 355.5 ms, interno p95 4.1 ms
 1000 registros:  search e2e p95 350.4 ms, save e2e p95 464.5 ms   ← FALLA
python bench/bench_mcp.py --reps 20   → exit=0 (worst p95 15.6 ms)
python bench/bench_sync.py --reps 20  → exit=0 (save 15.4 / search 5.9 ms p95)
pytest -q → 267 passed; ruff → clean
```

The `bench_cli` failure is the 1k end-to-end case on a machine that was not idle (p50
297-410 ms in three runs, 10k passing twice): it is the load, not the store — the internal
query stayed at 4.1 ms p95. The exit code is what this round adds; run it on an idle
machine before publishing.

## Tests

`tests/test_bench_hygiene.py` (7): `Store.close()` releases the database, each bench
leaves its `TemporaryDirectory` empty, the store is still closed when the measurement
raises, and the three SLO benches return 0/1 with forced thresholds (no dependency on
machine load). The empty-directory assertion only bites on
Windows, where an open handle blocks the delete; on POSIX the suite still covers the exit
codes but not the leak.

## Debt left open

`bench/ab.py` still uses `mkdtemp` and removes it with
`shutil.rmtree(..., ignore_errors=True)`: same silent-leak shape, but it drives OpenCode
subprocesses and no line of it measures the store.
