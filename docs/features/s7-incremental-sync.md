# S7: incremental sync

**Goal.** Two writers over 10,000 memories must not pay a full rebuild on every external
event. Target: `save` and `search` p95 < 50 ms when the other writer just appended.

**Scope.** `Store` sync only. No schema change, no new dependency and no change to the
JSONL format or the public API.

## Change

- `meta` keeps `jsonl_offset` (bytes already applied) and `jsonl_hash` (sha1 of that
  prefix), next to the existing `(size, mtime_ns)` fingerprint.
- `_sync` still fires on a fingerprint change, but `_catch_up` applies only the suffix:
  parse the complete new lines, apply them in one transaction and advance the offset.
- `save` syncs **before** appending. The local write no longer finds an unseen fingerprint
  and rebuilds: it catches up and then appends.
- The full rebuild remains the fallback when the prefix cannot be proven:
  - no offset stored (a database created before S7),
  - the file did not grow (truncation or a same-size replace),
  - the sha1 of the prefix changed (a `git checkout` of another branch that also grew),
  - the new events include an `archive` or a `save` for an id already in `mem`: their
    order depends on the global `ts`, not on append order,
  - the same id appears twice in the batch,
  - invalid JSON outside the tolerated last line.
- `rebuild` records the applied offset as the end of the bytes it read, so a valid last
  line without `\n` is already applied. The tail repair after a crash either completes
  that line (append) or truncates it (smaller than the offset, so the next sync rebuilds).
- The fingerprint is captured **before** reading, so an append that lands mid-catch-up is
  not certified and is applied on the next read.

## Acceptance criteria

- Tests: incremental append, several events at once, prefix equality with a fresh rebuild,
  update/archive fallback, truncation, torn tail and no certification of concurrent writes.
- Full suite and `ruff` clean.
- Two writers over 10k: p95 < 50 ms for `save` and `search`.

## Evidence (2026-11-09)

`python bench/bench_sync.py --reps 40`, two `Store` instances alternating a save and a
read over 10,000 seeded memories, same machine:

| Op | p50 | p95 | max |
|---|---|---|---|
| `save` | 11.6 ms | 13.6 ms | 30.6 ms |
| `search` | 3.2 ms | 4.8 ms | 5.1 ms |

Before S7 the same alternation forced a full rebuild per external event. Re-running the
loop with an explicit `rebuild()` before each operation (10 repetitions, this machine):

| Op | p50 | p95 |
|---|---|---|
| `save` | 3,294 ms | 3,773 ms |
| `search` | 3,200 ms | 5,508 ms |

- A rebuild alone with 10k measured 3.3-3.9 s in this run; the machine is slower than the
  1.3 s pass recorded in `BENCHMARKS.md`. The relative result is what matters: ~250x lower
  p50 on the writer path, and the 50 ms SLO passes with margin.
- 190 tests pass; `ruff` is clean.
- **Limit:** the prefix hash is recomputed from disk on every write and every changed sync.
  With 10k that is about 2 MB and stays under 5 ms; at 100k it becomes the next cost to
  measure against the 50 ms SLO.
- **Known window:** in `_append`, the hash is read after the write. A file replacement that
  grows inside that few-millisecond window could certify bytes that were not applied (see
  the `shortcut:` note in `store.py`). `rebuild` hashes the bytes it already read, so the
  window only exists on the append path.
