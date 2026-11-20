# Snippet for the AGENTS.md / CLAUDE.md of a project that uses cairn-mem

`cairn setup claude-code|opencode` writes this block for you (between
`<!-- cairn:begin -->` and `<!-- cairn:end -->`). Copy it by hand only for a harness
without a `setup` entry.

```markdown
## Project memory (cairn-mem)
@.cairn/MEMORY.md
<!-- If your harness does not support @imports: run `cairn render` at the start and read .cairn/MEMORY.md -->

Before you reply, ask: did I learn a reason that lives only in this conversation? If yes,
save it (one memory):

- The user gave a reason (a consumer, another timezone, a deadline, a constraint) and you
  changed the code because of it: that reason is not in the repo. Save it now.
  `cairn save --kind decision|gotcha --topic <stable/key> --title "<what>" --body "<the change, <=500 chars>" --why "<the user's reason>"`
- You took a decision with a reason, or confirmed a convention: same.
- With cairn as MCP, call the `save` tool instead of the command.

Do not save what the code or `git log` already says, task state, logs, secrets or customer
data. The same `--topic` replaces the previous memory. `cairn search` or the `search` tool
covers project and personal memory. Knowledge for any repo (commit style, user
preferences): save it with `--personal`. If an entry comes back with "⚠ review", check the
code before trusting it. At session close:
`cairn session save --summary "<done, pending>"`.
```
