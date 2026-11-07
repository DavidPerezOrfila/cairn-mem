# Snippet for the AGENTS.md / CLAUDE.md of a project that uses cairn-mem

```markdown
## Project memory (cairn-mem)
@.cairn/MEMORY.md
<!-- If your harness does not support @imports: run `cairn render` at the start and read .cairn/MEMORY.md -->

- If your harness supports MCP: start `cairn mcp` and use `search`, `save`, `get`,
  `context`, `save_session`. `context` already includes the last session recap, so you
  do not need to read it separately.
- If it does not: at the start of a task, run `cairn search "<terms>"` (at most 2 or 3
  searches; it covers project and personal memory). For detail, use `cairn get <id>`.
- Save ONLY when you make a decision with a reason, find a gotcha, or confirm a
  convention.
  `cairn save --kind decision|convention|gotcha|fact --topic <stable/key> --title "..." --body "<=500 chars" --why "..." [--anchor path/to/file]`
- Knowledge that applies to any repo (commit style, user preferences): save it with
  `--personal`. A normal `search` already finds it and marks it `[personal]`.
- When you close a session: `cairn session save --summary "<what you did, what is left>"`
  (no 500-character limit).
- Do NOT save: anything you can work out from the code or `git log`, temporary task
  state, logs, or secrets, credentials and customer data.
- The same `--topic` replaces the previous memory. Do not duplicate.
- If an entry comes back with "⚠ revisar", check the code before trusting it. If the
  code changed, rewrite the entry with the same `--topic`.
```
