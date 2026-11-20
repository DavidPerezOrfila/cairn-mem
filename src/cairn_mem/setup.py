"""`cairn setup <harness>`: deja el repo listo para usar cairn (S16).

Un harness es una fila de `HARNESSES`: su fichero de config MCP y su fichero de
instrucciones. Las rutas y formatos viven solo aquí.
"""

import json
from pathlib import Path
from typing import TypedDict

from cairn_mem.i18n import t
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
- If an entry comes back with "⚠ review", check the code before trusting it. If the
  code changed, rewrite the entry with the same `--topic`."""


class Harness(TypedDict):
    config: str
    config_path: tuple[str, ...]
    server: dict[str, object]
    base: dict[str, object]
    instructions: str
    label: str


HARNESSES: dict[str, Harness] = {
    "claude-code": {
        "config": ".mcp.json",
        "config_path": ("mcpServers", "cairn"),
        "server": {"command": "cairn", "args": ["mcp"]},
        "base": {},
        "instructions": "CLAUDE.md",
        "label": "Claude Code",
    },
    "opencode": {
        "config": "opencode.json",
        "config_path": ("mcp", "servers", "cairn"),
        "server": {"type": "local", "command": ["cairn", "mcp"]},
        "base": {"$schema": SCHEMA},
        "instructions": "AGENTS.md",
        "label": "OpenCode",
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
                t(
                    f"{path} is not strict JSON (comments?); add the block by hand:\n"
                    f"{block}",
                    f"{path} no es JSON estricto (¿comentarios?); añade el bloque a "
                    f"mano:\n{block}",
                )
            )
        if not isinstance(data, dict):
            # ValueError: la CLI lo imprime como error de usuario, no como bug.
            raise ValueError(
                t(
                    f"{path}: expected a JSON object",
                    f"{path}: se esperaba un objeto JSON",
                )
            )
    else:
        data = dict(base)
    node = data
    for key in keys[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            # ValueError: la CLI lo imprime como error de usuario, no como bug.
            raise ValueError(  # noqa: TRY004
                t(
                    f"{path}: '{key}' is not a JSON object",
                    f"{path}: '{key}' no es un objeto JSON",
                )
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
    # LF siempre: el fichero de instrucciones se commitea y el bloque es LF.
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
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


def _imports_agents(path: Path) -> bool:
    """¿El fichero de instrucciones ya importa `@AGENTS.md` (S21)?

    El harness lee el bloque a través del import, así que escribirlo también aquí lo
    duplicaría en el prompt.
    """
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().removeprefix("@") in ("AGENTS.md", "./AGENTS.md"):
            return True
    return False


def _remove_snippet(path: Path) -> bool:
    """Quita el bloque de cairn y restaura el fichero a como estaba."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    stop = text.find(END)
    start = text.rfind(BEGIN, 0, stop) if stop != -1 else -1
    if start == -1:
        return False
    updated = text[:start].rstrip("\n") + "\n" + text[stop + len(END) + 1 :]
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
    if spec["instructions"] != "AGENTS.md" and _imports_agents(instructions):
        removed = _remove_snippet(instructions)
        state = (
            t("duplicate block removed", "bloque duplicado eliminado")
            if removed
            else t("already there", "ya estaba")
        )
        snippet_line = t(
            f"instructions: {instructions} (imports @AGENTS.md; {state})",
            f"instrucciones: {instructions} (importa @AGENTS.md; {state})",
        )
    else:
        snippet_changed = _write_snippet(instructions)
        state = (
            t("updated", "actualizado")
            if snippet_changed
            else t("already there", "ya estaba")
        )
        snippet_line = t(
            f"instructions: {instructions} ({state})",
            f"instrucciones: {instructions} ({state})",
        )
    config_state = (
        t("updated", "actualizado")
        if config_changed
        else t("already there", "ya estaba")
    )
    lines = [
        f"config: {config} ({config_state})",
        snippet_line,
    ]
    try:
        data_dir()
    except FileNotFoundError:
        lines.append(
            t(
                "no .cairn/ in this tree: run 'cairn init'",
                "sin .cairn/ en este árbol: ejecuta 'cairn init'",
            )
        )
    lines.append(
        t(
            f"restart {spec['label']} in this repo",
            f"reinicia {spec['label']} en este repo",
        )
    )
    return lines
