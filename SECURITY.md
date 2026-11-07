# Security

## Reporting a vulnerability

Please use GitHub private vulnerability reporting:
https://github.com/DavidPerezOrfila/cairn-mem/security/advisories/new

Do not open a public issue with a working exploit or with real memory contents. You can
expect an initial reply within 7 days.

## Supported versions

Only the latest release on PyPI receives fixes.

## What this project guarantees

- Secrets are rejected, never redacted. Before writing an event, `save` refuses cloud
  keys, `BEGIN ... PRIVATE KEY`, JWTs (`eyJ...`), provider tokens (`ghp_`, `gho_`, `ghu_`,
  `ghs_`, `ghr_`, `github_pat_`, `glpat-`, `sk-proj-`, `sk-ant-`, `AIza`),
  `password|secret|token|api_key` assignments and URLs with `user:pass@`. A rejected save
  writes nothing.
- Memory is local by default. `.cairn/MEMORY.md` and `.cairn/cairn.db` are derived and
  gitignored. `.cairn/events.jsonl` shows up in diffs when you commit it, so treat every
  entry as public to the repository.
- No network, no LLM. The CLI and the MCP server read and write files only.
- MCP writes go through a single store per scope. Concurrent processes appending to
  `.cairn/events.jsonl` are safe because of `O_APPEND` plus one `os.write` per event.

Out of scope: the contents of memories you chose to commit, and secrets pasted into an
agent session that never reached `cairn save`.
