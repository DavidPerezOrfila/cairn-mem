# cairn-mem

Project memory for coding agents, stored as files you can read.

[![PyPI](https://img.shields.io/pypi/v/cairn-mem.svg)](https://pypi.org/project/cairn-mem/)
[![Python](https://img.shields.io/pypi/pyversions/cairn-mem.svg)](https://pypi.org/project/cairn-mem/)
[![CI](https://github.com/DavidPerezOrfila/cairn-mem/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidPerezOrfila/cairn-mem/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An agent finishes a session and the next one starts from zero. You explain again why
the auth flow works that way and which migration is risky.

Cairn keeps that context in `.cairn/events.jsonl`, inside the repository. Each entry
is a short decision, convention, gotcha or fact, with the reason behind it. A new
session loads a compact summary and searches the rest when it needs it. Long session
summaries live in `.cairn/sessions.jsonl`; knowledge that applies to every repo can go
to a personal store in `~/.cairn`.

```console
$ cairn save --kind decision --topic storage/fts5 \
    --title "Use FTS5, not embeddings" \
    --body "BM25 over SQLite is enough for 10k memories" \
    --why "The internal query stays under 6 ms"

$ cairn search "search backend"
a1b2c3d4e5f6  decision  Use FTS5, not embeddings - BM25 over SQLite is enough...
```

There is nothing to run in the background and no extra binary to install. Python
3.10 or newer and the standard library are enough.

## How it compares

Memory tools usually keep entries in a local database and let a model decide what to
save. That works until you need to review the memory, share it with a teammate, or
explain why the agent believes something.

| | Database-backed memory tools | cairn-mem |
|---|---|---|
| Storage | Local database, outside the repo | `.cairn/events.jsonl`, plain text |
| Review | Open the database | Read the diff in a pull request |
| Sharing | Export and import | `git clone`, or local-only by default |
| Who writes | Often an LLM extracts a summary | The agent writes what it learned, with a reason |
| Output | Varies with the model | Same input gives the same result |
| Runtime | A server or a separate binary | Python standard library |

Cairn is a place for the things you would otherwise repeat in the next session. Task
state and logs belong in the task tracker.

## Install

```bash
uv tool install cairn-mem     # or: pipx install cairn-mem
# development:
pip install -e ".[dev]"
```

SQLite with FTS5 ships with CPython on Linux, macOS and Windows. The core has no
third-party dependencies; the `dev` extra only adds pytest and ruff.

MCP, session summaries, personal scope and the legacy importer ship in 0.2.0.
`uv tool install cairn-mem` (or `pipx install cairn-mem`) gets the latest release.

## Quickstart

```bash
cairn init                 # .cairn/ for this repo, local-only
cairn init --share         # commit events.jsonl so the team shares memory
```

Save something worth keeping:

```bash
cairn save \
  --kind gotcha \
  --topic auth/redirect \
  --title "OAuth callback must match exactly" \
  --body "redirect_uri is compared byte for byte; trailing slashes fail" \
  --why "Spent two hours debugging a 400 from the provider" \
  --anchor src/auth.py
```

Find it again:

```bash
cairn search "oauth redirect"     # id, kind, title, snippet, stale flag
cairn get a1b2c3d4e5f6            # full memory
cairn check                       # memories whose anchor file changed
cairn session save --summary "## Goal ..."   # long recap, kept out of MEMORY.md
cairn search "commit style" --personal       # knowledge shared by every repo
```

### MCP

One process, five tools (`save`, `search`, `get`, `context`, `save_session`), JSON-RPC over
stdio:

```json
{
  "mcpServers": {
    "cairn": { "command": "cairn", "args": ["mcp"] }
  }
}
```

The server keeps the index open, so a tool call takes a few milliseconds instead of
paying Python startup on every request. `save` and `search` accept
`"scope": "personal"`. `context` returns `MEMORY.md` plus the last session recap,
so a new session starts where the previous one stopped.

### Migrating from another memory store

```bash
cairn import legacy --db <path> --dry-run   # counts without writing
cairn import legacy --db <path>             # project rows to .cairn/, global rows to ~/.cairn
```

Running it again is a no-op: ids are derived from the source observation id.

### Any other harness

Copy the snippet from [`docs/AGENT_SNIPPET.md`](docs/AGENT_SNIPPET.md) into your
`AGENTS.md` or `CLAUDE.md`. The agent reads `MEMORY.md` at the start of a task,
searches before writing, and saves only what is worth keeping.

## How it works

```text
agent ── MCP or shell ──> cairn ──> .cairn/events.jsonl   (truth, append-only)
                                    ├── .cairn/sessions.jsonl (long recaps)
                                    ├── cairn.db          (derived, FTS5)
                                    └── MEMORY.md         (L0, <= 3000 chars)
```

`MEMORY.md` is the compact summary an agent reads at startup. `cairn search` returns
id, kind, title, snippet and a `stale` flag; `cairn get` returns the full entry.

An entry can point to a file with `--anchor`. Cairn stores a hash of that file, and
when the file changes the entry is flagged `⚠ revisar`. Nothing is deleted and nothing
is hidden. Saving with the same `topic` replaces the previous entry, so the list stays
current.

Only `events.jsonl` is the source of truth. The database and `MEMORY.md` are derived;
delete either one and the next command rebuilds it. `sessions.jsonl` is append-only
and local: session recaps are continuity, not curated memory.

## What it stores

Four kinds, with a body of at most 500 characters:

| Kind | Use it for |
|---|---|
| `decision` | A choice and its reason: storage, architecture, a library |
| `convention` | How this repo does things: naming, commits, structure |
| `gotcha` | A trap that cost time, such as a platform quirk or an API failure |
| `fact` | Stable context that is not obvious from the code |

Cairn refuses text that looks like a secret, such as cloud keys, private keys, JWTs,
`password = ...` or URLs with credentials. It does not redact them silently.

## Measurements

From one Windows 11 machine with 10k memories and an idle CPU
([details](docs/BENCHMARKS.md)):

| Operation | p95 |
|---|---|
| `search` via CLI, including Python startup | 304 ms |
| `save` via CLI, including the summary render | 451 ms |
| `search` via MCP tool call | 8 ms |
| `save` via MCP tool call | 23 ms |
| Internal query | 5.9 ms |

Retrieval precision@3 on the bundled golden set is 30/30. A small paired test, 8 tasks
run twice, went from 0/16 correct answers and 26,826 tokens without memory to 16/16 and
20,982 tokens with it. The sample is too small to prove much, but the direction was
consistent.

## Commands

| Command | Purpose |
|---|---|
| `cairn init [--share]` | Create `.cairn/`; `--share` versions `events.jsonl` |
| `cairn save` | Store a decision, convention, gotcha or fact |
| `cairn search "terms"` | Ranked active memories |
| `cairn get <id>` | Full memory |
| `cairn archive <id>` | Stop returning a memory |
| `cairn check` | List memories whose anchor changed |
| `cairn render` | Regenerate and print `MEMORY.md` |
| `cairn rebuild` | Rebuild the index from `events.jsonl` |
| `cairn session save\|list\|get [--personal]` | Session recaps, separate from curated memory |
| `cairn import legacy --db <path> [--dry-run]` | Migrate observations from another SQLite store |
| `cairn mcp` | Serve MCP over stdio |

`--json` is available on `save`, `search`, `get`, `check`, `session` and `import` for
agent consumption. `save`, `search` and `archive` accept `--personal`; `get` checks
both stores.

## Design choices

Saving is explicit. No model decides what to keep, and nothing calls an LLM, so the
same input produces the same memory store.

Memory stays local unless you run `cairn init --share`. Internal context does not
leave the machine by default.

The JSONL format and anchor hashes work the same on Linux, macOS and Windows. CI runs
the test suite on all three.

New capabilities need a measurement that justifies them. The backlog lives in
[`PLAN.md`](PLAN.md).

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests bench
python bench/bench_mcp.py --reps 20
```

See [`PLAN.md`](PLAN.md) for milestones, [`docs/DESIGN.md`](docs/DESIGN.md) for the
design and [`docs/DECISIONS.md`](docs/DECISIONS.md) for the reasoning behind each
trade-off.

## License

MIT. See [`LICENSE`](LICENSE).
