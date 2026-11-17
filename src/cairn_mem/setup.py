"""`cairn setup <harness>`: deja el repo listo para usar cairn (S16).

Un harness es una fila de `HARNESSES`: su fichero de config MCP y su fichero de
instrucciones. Las rutas y formatos viven solo aquí.
"""

import json
from pathlib import Path

from cairn_mem.paths import data_dir

BEGIN = "<!-- cairn:begin -->"
END = "<!-- cairn:end -->"

SCHEMA = "https://opencode.ai/config.json"

SNIPPET = """## Project memory (cairn-mem)
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
  code changed, rewrite the entry with the same `--topic`."""

HARNESSES = {
    "claude-code": {
        "config": ".mcp.json",
        "config_path": ("mcpServers", "cairn"),
        "server": {"command": "cairn", "args": ["mcp"]},
        "base": {},
        "instructions": "CLAUDE.md",
        "restart": "reinicia Claude Code en este repo",
    },
    "opencode": {
        "config": "opencode.json",
        "config_path": ("mcp", "servers", "cairn"),
        "server": {"type": "local", "command": ["cairn", "mcp"]},
        "base": {"$schema": SCHEMA},
        "instructions": "AGENTS.md",
        "restart": "reinicia OpenCode en este repo",
    },
}


def _nested(keys, value, base):
    node = dict(base)
    cursor = node
    for key in keys[:-1]:
        cursor[key] = {}
        cursor = cursor[key]
    cursor[keys[-1]] = value
    return node


def _merge_config(path: Path, keys, server, base) -> bool:
    """Conserva el resto del fichero: solo toca la clave del servidor."""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            block = json.dumps(
                _nested(keys, server, base), indent=2, ensure_ascii=False
            )
            raise ValueError(
                f"{path} no es JSON estricto (¿comentarios?); añade el bloque a mano:\n"
                f"{block}"
            )
    else:
        data = dict(base)
    node = data
    for key in keys[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            # ValueError: la CLI lo imprime como error de usuario, no como bug.
            raise ValueError(  # noqa: TRY004
                f"{path}: '{key}' no es un objeto JSON"
            )
    if node.get(keys[-1]) == server:
        return False
    node[keys[-1]] = server
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return True


def _write_snippet(path: Path) -> bool:
    block = f"{BEGIN}\n{SNIPPET}\n{END}\n"
    if not path.exists():
        path.write_text(block, encoding="utf-8", newline="\n")
        return True
    text = path.read_text(encoding="utf-8")
    stop = text.find(END)
    start = text.rfind(BEGIN, 0, stop) if stop != -1 else -1
    if start != -1:
        updated = text[:start] + block + text[stop + len(END) + 1 :]
    else:
        updated = text.rstrip("\n") + "\n\n" + block
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8", newline="\n")
    return True


def setup(harness: str, directory: Path) -> list[str]:
    spec = HARNESSES[harness]
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / spec["config"]
    instructions = directory / spec["instructions"]
    config_changed = _merge_config(
        config, spec["config_path"], spec["server"], spec["base"]
    )
    snippet_changed = _write_snippet(instructions)
    lines = [
        f"config: {config} ({'actualizado' if config_changed else 'ya estaba'})",
        (
            f"instrucciones: {instructions} "
            f"({'actualizado' if snippet_changed else 'ya estaba'})"
        ),
    ]
    try:
        data_dir()
    except FileNotFoundError:
        lines.append("sin .cairn/ en este árbol: ejecuta 'cairn init'")
    lines.append(spec["restart"])
    return lines
