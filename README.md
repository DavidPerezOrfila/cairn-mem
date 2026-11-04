<div align="center">

<h1>cairn-mem</h1>

<p><strong>Project memory for coding agents, stored as plain files you can review.</strong></p>

[![PyPI](https://img.shields.io/pypi/v/cairn-mem.svg)](https://pypi.org/project/cairn-mem/)
[![Python](https://img.shields.io/pypi/pyversions/cairn-mem.svg)](https://pypi.org/project/cairn-mem/)
[![CI](https://github.com/DavidPerezOrfila/cairn-mem/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidPerezOrfila/cairn-mem/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Dependencies: 0](https://img.shields.io/badge/runtime%20dependencies-0-brightgreen.svg)](pyproject.toml)

[Install](#install) · [Quickstart](#quickstart) · [Agents](#use-it-from-your-agent) · [How it works](#how-it-works) · [Benchmarks](#benchmarks) · [Commands](#commands)

</div>

An agent finishes a session and the next one starts from zero. You explain again why
the auth flow works that way, which migration is risky, and why the team uses that
commit convention.

Cairn keeps that context in `.cairn/events.jsonl`, inside the repository: short
decisions, conventions, gotchas and facts, each one with the reason behind it. A new
session loads a compact summary and searches the rest when it needs it.

```console
$ cairn save --kind decision --topic storage/fts5 \
    --title "Use FTS5, not embeddings" \
    --body "BM25 over SQLite is enough for 10k memories" \
    --why "The internal query stays under 6 ms"
7a5a07d26632

$ cairn search "fts5"
7a5a07d26632  decision  Use FTS5, not embeddings — BM25 over SQLite is enough for 10k memories
```

No daemon, no server, no extra binary. Python 3.10 or newer and the standard library
are enough.

## Why cairn

- **Memory you can review.** Plain JSONL in the repo. When you share it, memory changes
  go through a pull request like any other code change.
- **Explicit, not magic.** The agent writes what it learned and why. No model decides
  what to keep, no embeddings, no hidden pipeline.
- **Portable.** A CLI for any harness with a shell, plus an MCP server for clients that
  speak the protocol.
- **Fast where it matters.** A search through 10k memories takes a few milliseconds over MCP.
- **Local by default.** Nothing leaves the machine unless you run `cairn init --share`.
- **Deterministic.** The same store and the same query give the same ranking. Nothing
  depends on a model or a network call.

## Install

```bash
uv tool install cairn-mem     # or: pipx install cairn-mem

# development
pip install -e ".[dev]"
```

Python 3.10+, no third-party runtime dependencies. The `dev` extra only adds pytest
and ruff. Cairn needs SQLite with FTS5, which ships with the usual CPython builds on
Linux, macOS and Windows.

## Quickstart

Create the store for the current repository:

```bash
cairn init                 # .cairn/ here, local-only
cairn init --share         # version events.jsonl so the team shares memory
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

`--anchor` stores a hash of an existing file. If that file changes later, the memory
is flagged for review instead of silently going stale.

Find it again:

```bash
cairn search "oauth redirect"                # id, kind, topic, title, snippet, stale flag
cairn get a1b2c3d4e5f6                       # full memory, including the reason
cairn check                                  # memories whose anchor file changed
cairn session save --summary "## Goal ..."   # long recap, kept out of MEMORY.md
cairn search "commit style" --personal       # knowledge shared by every repo
```

Anything you would otherwise repeat in the next session belongs here. Task state,
logs and chat transcripts do not.

## Use it from your agent

### MCP

One process, five tools (`save`, `search`, `get`, `context`, `save_session`),
JSON-RPC over stdio:

```json
{
  "mcpServers": {
    "cairn": { "command": "cairn", "args": ["mcp"] }
  }
}
```

The server keeps the SQLite index open, so a tool call costs a few milliseconds
instead of paying Python startup every time. `save`, `search` and `save_session`
accept `"scope": "personal"`. `context` returns `MEMORY.md` plus the last session
recap, so a new session starts where the previous one stopped.

### Any other harness

Copy the snippet from [`docs/AGENT_SNIPPET.md`](docs/AGENT_SNIPPET.md) into your
`AGENTS.md` or `CLAUDE.md`. The agent reads `MEMORY.md` at the start of a task,
searches before writing, and saves only what is worth keeping.

## How it works

```text
agent ── MCP or shell ──> cairn ──> .cairn/events.jsonl     (truth, append-only)
                                    ├── .cairn/sessions.jsonl (long recaps)
                                    ├── cairn.db            (derived, FTS5)
                                    └── MEMORY.md           (L0, <= 3000 chars)
```

`MEMORY.md` is the compact summary an agent reads at startup. It is built round-robin
across kinds, so a noisy kind cannot push the others out of the budget. Each line shows
the topic key when the entry has one.

| Level | What | Size |
|---|---|---|
| L0 | `.cairn/MEMORY.md`, loaded at startup | ≤ 3000 characters |
| L1 | `cairn search "<terms>"` | about 50 tokens per result |
| L2 | `cairn get <id>` | full entry, body ≤ 500 characters |

Search covers the title, body, reason, topic key and anchor path, so `storage/fts5` or
`src/auth.py` find the entry without remembering the title.

Only `events.jsonl` is the source of truth. `cairn.db` is rebuilt automatically when
it is missing or out of date. `MEMORY.md` is regenerated by `save`, `archive`,
`rebuild` or `cairn render`. `sessions.jsonl` is append-only and local: session recaps
are continuity, not curated memory.

An entry can point to a file with `--anchor`. Cairn stores a hash of that file and
flags the entry with `⚠ revisar` when the file changes. Stale entries are never
deleted or hidden automatically; `cairn archive <id>` is the explicit way to retire
one. Saving with the same `topic` supersedes the previous entry, so the list stays
current.

## What it stores

Four kinds, with a title of at most 200 characters and a body of at most 500:

| Kind | Use it for |
|---|---|
| `decision` | A choice and its reason: storage, architecture, a library |
| `convention` | How this repo does things: naming, commits, structure |
| `gotcha` | A trap that cost time, such as a platform quirk or an API failure |
| `fact` | Stable context that is not obvious from the code |

Cairn refuses text that looks like a secret, such as cloud keys, private keys, JWTs,
`password = ...` or URLs with credentials. It does not redact them silently.

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
| Output | Varies with the model | Deterministic ranking, no model in the loop |
| Runtime | A server or a separate binary | Python standard library |

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

## Benchmarks

Windows 11, 10k memories, idle CPU, 2026-11-04. CLI numbers include Python startup;
MCP numbers are in-process tool calls ([all measurements](docs/BENCHMARKS.md)):

| Operation | p95 |
|---|---|
| `cairn search` via CLI | 150.6 ms |
| `cairn save` via CLI, summary render included | 137.8 ms |
| `search` via MCP tool call | 2.3 ms |
| `save` via MCP tool call | 9.4 ms |
| `context` via MCP tool call | 5.8 ms |
| Internal FTS5 query | 2.2 ms |

Retrieval precision@3 on the bundled golden set is 30/30. A small paired test, 8 tasks
run twice, went from 0/16 correct answers and 26,826 tokens without memory to 16/16
and 20,982 tokens with it. The sample is too small to prove much, but the direction was
consistent ([details](docs/AB_RESULTS.md)).

## Migrating from another memory store

```bash
cairn import legacy --db <path> --dry-run   # counts without writing
cairn import legacy --db <path>             # project rows to .cairn/, global rows to ~/.cairn
```

Running it again is a no-op: ids are derived from the source observation id.

## Design choices

Saving is explicit. No model decides what to keep, and nothing calls an LLM, so the
same store and query produce the same ranking.

Memory stays local unless you run `cairn init --share`. Internal context does not
leave the machine by default.

The JSONL format and anchor hashes work the same on Linux, macOS and Windows; anchor
hashes normalize CRLF to LF. CI runs the suite on all three systems and on Python 3.10
and 3.14.

New capabilities need a measurement that justifies them. `hits`, decay, embeddings
and passive capture stay in the backlog until a benchmark or a real user shows a gap
([`PLAN.md`](PLAN.md)).

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

## Contributing

Issues and pull requests are welcome. Keep changes small, add a test for behavior
changes, and run `pytest -q` plus `ruff check src tests bench` before opening a PR.
The PR template lists the full checklist; [`AGENTS.md`](AGENTS.md) documents the
project conventions.

If cairn saves you from explaining the same thing twice, a star helps other people
find it.

## License

MIT. See [`LICENSE`](LICENSE).
