# S10: `cairn doctor`

## Goal

One local command answers "is this store healthy and is the binary I run the one I
think?". No network, no repair beyond the derived files every command already refreshes.

## Scope

- New `doctor.py` behind `cairn doctor [--json] [--personal]`, imported lazily so CLI
  startup stays lean.
- Checks: Python version, SQLite with FTS5, how many `cairn` executables resolve on
  `PATH`, store root, `.gitignore` entries, `events.jsonl` line validity (via
  `store.parse_event`), `sessions.jsonl` replay, DB fingerprint vs `events.jsonl`, L0
  characters vs the 3000 budget, stale anchors.
- Exit code 1 if any check is `fail`; warnings (`warn`) keep it 0.
- Out of scope: repairing the store, checking for releases on PyPI, writing events.

## Decision: no `cairn update`

Updating is the package manager's job (`uv tool upgrade cairn-mem`,
`pipx upgrade cairn-mem`, `pip install -U cairn-mem`): all three replace the installed
version in place. A self-updater inside cairn would need network access (today
`SECURITY.md` guarantees none), a subprocess dependency on pip/uv/pipx, and a guess about
which of several installs to replace. The real failure mode is two binaries, which
`doctor` now reports. The one-liners go to the README.

## Acceptance

- `pytest -q` covers: healthy store exits 0, JSON shape, corrupt event line fails with
  `events.jsonl línea N`, missing `.gitignore` entries warn, stale anchors are counted,
  two `PATH` installs warn, no store fails without creating `.cairn/`.
- `cairn doctor` on this repo exits 0 after `cairn init` refreshes `.cairn/.gitignore`.
- README documents the upgrade commands; `docs/DECISIONS.md` records why the command does
  not exist.

## Pre-release review (2026-11-11)

13 adversarial scenarios outside the suite passed (torn tails, desynced DB, two installs,
`CAIRN_DIR` pointing nowhere, `events.jsonl` byte-identical). It found one real bug, fixed
as S10.1: a `sessions.jsonl` line that is valid JSON but not an object (`[1]`) raised
`AttributeError` and crashed `doctor` with a traceback. `Sessions._records` now rejects it
with `sessions.jsonl línea N`, and `doctor` reports it as a failed check.
