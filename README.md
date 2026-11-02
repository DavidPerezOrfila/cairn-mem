# cairn-mem

**The project memory that travels with your code.**

[![PyPI](https://img.shields.io/pypi/v/cairn-mem.svg)](https://pypi.org/project/cairn-mem/)
[![Python](https://img.shields.io/pypi/pyversions/cairn-mem.svg)](https://pypi.org/project/cairn-mem/)
[![CI](https://github.com/DavidPerezOrfila/cairn-mem/actions/workflows/ci.yml/badge.svg)](https://github.com/DavidPerezOrfila/cairn-mem/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Coding agents forget everything when the session ends. Cairn gives them a small,
typed memory that lives **inside your repository**: decisions, conventions, gotchas
and facts, each with the reason behind it.

No daemon. No Go binary. No API key. No LLM calls. One `pip install` and a JSONL file
you can read, diff and review in a pull request.

```console
$ cairn save --kind decision --topic storage/fts5 \
    --title "Use FTS5, not embeddings" \
    --body "BM25 over SQLite is enough for 10k memories" \
    --why "Internal query stays under 6 ms"

$ cairn search "search backend"
a1b2c3d4e5f6  decision  Use FTS5, not embeddings — BM25 over SQLite is enough…
```

## Why another memory tool?

Most agent memory lives in an opaque local database and is written by an LLM. That
works until you need to review it, share it with a teammate, move it to another
machine, or explain why the agent believes something.

Cairn takes the opposite trade-off:

| | Typical agent memory | cairn-mem |
|---|---|---|
| Storage | Local database, invisible | `.cairn/events.jsonl`, plain text |
| Review | Open a DB | Read the diff in a PR |
| Sharing | Export/import | `git clone` (or local-only by default) |
| Extraction | LLM summarizes and guesses | The agent writes what it learned, with a reason |
| Results | Change with the model | Deterministic, same input → same output |
| Runtime | Server or binary to install | Python stdlib only |
| Harness support | MCP-only | MCP or any shell |

Cairn is not a chat log, a vector store, or an auto-summarizer. It is a small set of
durable facts that a new session can load in under a second.

## Install

```bash
uv tool install cairn-mem     # or: pipx install cairn-mem
# development:
pip install -e ".[dev]"
```

Python 3.10+. SQLite with FTS5 ships with CPython on Linux, macOS and Windows.

> MCP support lands in **0.2.0**. The latest PyPI release (0.1.0) provides the CLI;
> use `main` until 0.2.0 is published.

## Quickstart

```bash
cairn init                 # .cairn/ for this repo (local-only by default)
cairn init --share         # commit events.jsonl so the team shares memory
```

Save something worth remembering:

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
```

### MCP

One process, four tools (`save`, `search`, `get`, `context`), JSON-RPC over stdio:

```json
{
  "mcpServers": {
    "cairn": { "command": "cairn", "args": ["mcp"] }
  }
}
```

The server keeps the index open, so a tool call takes milliseconds instead of paying
Python startup on every request.

### Any other harness

Copy the snippet from [`docs/AGENT_SNIPPET.md`](docs/AGENT_SNIPPET.md) into your
`AGENTS.md` or `CLAUDE.md`. The agent reads `MEMORY.md` at start, searches before
writing, and saves only what is worth keeping.

## How it works

```text
agent ── MCP or shell ──> cairn ──> .cairn/events.jsonl   (truth, append-only)
                                    ├── cairn.db          (derived, FTS5)
                                    └── MEMORY.md         (L0, ≤ 3000 chars)
```

- **L0** — a compact `MEMORY.md` (≤ 3000 characters) the agent loads at session start.
- **L1** — `search` returns id, kind, title, snippet and a `stale` flag.
- **L2** — `get` returns the full memory, body and reason.
- **Anchors** — an optional file path plus its hash. When the file changes, the memory
  is flagged `⚠ revisar`; nothing is deleted or silently hidden.
- **Topics** — saving with the same `topic` supersedes the previous memory, so the
  store stays small and current.

Everything except `events.jsonl` is derived and regenerable. Delete the database and
the next command rebuilds it.

## What it stores

Four kinds, one body of at most 500 characters:

| Kind | Use it for |
|---|---|
| `decision` | A choice with a reason: storage, architecture, a library |
| `convention` | How this repo does things: naming, commits, structure |
| `gotcha` | A trap that cost time: platform quirks, API failures |
| `fact` | Stable context that is not obvious from the code |

Cairn **rejects** text that looks like a secret (cloud keys, private keys, JWTs,
`password = ...`, URLs with credentials) instead of redacting it silently.

It does not store task state, logs, or anything derivable from `git log`. That rule is
what keeps retrieval precise.

## Measured, not promised

Numbers from a Windows 11 machine, 10k memories, idle system
([details](docs/BENCHMARKS.md)):

| Operation | p95 |
|---|---|
| `search` via CLI (includes Python startup) | 304 ms |
| `save` via CLI (includes L0 render) | 451 ms |
| `search` via MCP tool call | 8 ms |
| `save` via MCP tool call | 23 ms |
| Internal query | 5.9 ms |

Retrieval precision@3 on the bundled golden set: **30/30**.
A small paired pilot (8 tasks, 2 repetitions) went from **0/16** correct answers and
26,826 tokens without memory to **16/16** and 20,982 tokens with it. Sample size is
small; treat it as directional, not proof.

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
| `cairn mcp` | Serve MCP over stdio |

`--json` is available on `save`, `search`, `get` and `check` for agent consumption.

## Design constraints

- **No LLM in any path.** Saving is explicit and deterministic.
- **No dependencies.** The core is Python stdlib; `dev` only adds pytest and ruff.
- **Local-only by default.** Memory can contain internal context; sharing is opt-in.
- **Windows first, not Windows only.** UTF-8 everywhere, LF files, CRLF-insensitive
  anchor hashes, CI on Linux, macOS and Windows.
- **Small surface.** Additions need a measurement that justifies them, not a hunch.

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
