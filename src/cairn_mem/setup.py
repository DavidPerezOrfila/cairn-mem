"""`cairn setup <harness>`: deja el repo listo para usar cairn (S16).

Un harness es una fila de `HARNESSES`: su fichero de config MCP y su fichero de
instrucciones. Las rutas y formatos viven solo aquí.
"""

import json
import sys
from pathlib import Path
from typing import Any, TypedDict

from cairn_mem.i18n import t
from cairn_mem.paths import data_dir, ignore_update, safe_path, write_if_changed

BEGIN = "<!-- cairn:begin -->"
END = "<!-- cairn:end -->"

SCHEMA = "https://opencode.ai/config.json"

SNIPPET = """## Project memory (cairn-mem)
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
`cairn session save --summary "<done, pending>"`."""


class Harness(TypedDict):
    config: str
    config_path: tuple[str, ...]
    server: dict[str, object]
    base: dict[str, object]
    instructions: str
    hook: str
    hook_asset: str
    label: str


HARNESSES: dict[str, Harness] = {
    "claude-code": {
        "config": ".mcp.json",
        "config_path": ("mcpServers", "cairn"),
        "server": {"command": "cairn", "args": ["mcp"]},
        "base": {},
        "instructions": "CLAUDE.md",
        "hook": ".claude/hooks/cairn_stop.py",
        "hook_asset": "claude_code.py",
        "label": "Claude Code",
    },
    "opencode": {
        "config": "opencode.json",
        "config_path": ("mcp", "servers", "cairn"),
        "server": {"type": "local", "command": ["cairn", "mcp"]},
        "base": {"$schema": SCHEMA},
        "instructions": "AGENTS.md",
        "hook": ".opencode/plugins/cairn-stop/index.ts",
        "hook_asset": "index.ts",
        "label": "OpenCode",
    },
}

# Los hooks medidos: el asset del paquete es la fuente de verdad al instalar.
HOOK_ASSET = Path(__file__).parent / "assets" / "stop" / "index.ts"
CC_HOOK_ASSET = Path(__file__).parent / "assets" / "stop" / "claude_code.py"
CLAUDE_HOOK_EVENTS = ("SessionStart", "Stop")


def _load_claude_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        data: dict[str, Any] = {}
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError:
            raise ValueError(
                t(
                    f"{path} is not strict JSON (comments?)",
                    f"{path} no es JSON estricto (¿comentarios?)",
                )
            )
        if not isinstance(data, dict):
            raise ValueError(
                t(
                    f"{path}: expected a JSON object",
                    f"{path}: se esperaba un objeto JSON",
                )
            )
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(  # noqa: TRY004
            t(
                f"{path}: 'hooks' is not a JSON object",
                f"{path}: 'hooks' no es un objeto JSON",
            )
        )
    for event in CLAUDE_HOOK_EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(  # noqa: TRY004
                t(
                    f"{path}: 'hooks.{event}' is not a JSON array",
                    f"{path}: 'hooks.{event}' no es un array JSON",
                )
            )
        for index, group in enumerate(groups):
            if not isinstance(group, dict):
                raise ValueError(  # noqa: TRY004
                    t(
                        f"{path}: 'hooks.{event}[{index}]' is not a JSON object",
                        f"{path}: 'hooks.{event}[{index}]' no es un objeto JSON",
                    )
                )
            commands = group.get("hooks", [])
            if not isinstance(commands, list):
                raise ValueError(  # noqa: TRY004
                    t(
                        f"{path}: 'hooks.{event}[{index}].hooks' is not a JSON array",
                        f"{path}: 'hooks.{event}[{index}].hooks' no es un array JSON",
                    )
                )
            if any(not isinstance(command, dict) for command in commands):
                raise ValueError(
                    t(
                        f"{path}: 'hooks.{event}[{index}].hooks' must contain JSON objects",
                        f"{path}: 'hooks.{event}[{index}].hooks' debe contener objetos JSON",
                    )
                )
    return data


def _save_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 0
    count = 0
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("op") == "save":
            count += 1
    return count


def _hook_updates(harness: str, directory: Path) -> list[tuple[Path, bytes]]:
    spec = HARNESSES[harness]
    script = safe_path(directory, spec["hook"])
    asset = Path(__file__).parent / "assets" / "stop" / spec["hook_asset"]
    content = asset.read_bytes()
    if script.exists() and script.read_bytes() != content:
        raise ValueError(
            t(
                f"{script} already exists and is not the cairn hook; remove or rename it",
                f"{script} ya existe y no es el hook de cairn; elimínalo o renómbralo",
            )
        )
    updates = [(script, content)]
    if harness != "claude-code":
        return updates
    settings_path = safe_path(directory, ".claude/settings.json")
    safe_path(directory, ".cairn-nudge.log")
    settings = _load_claude_settings(settings_path)
    hook = {
        "type": "command",
        "command": sys.executable,
        "args": ["-I", script.as_posix()],
    }
    settings_changed = False
    for event in CLAUDE_HOOK_EVENTS:
        groups = settings["hooks"][event]
        if not any(
            existing == hook
            for group in groups
            for existing in group.get("hooks", [])
        ):
            groups.append({"hooks": [hook]})
            settings_changed = True
    if settings_changed:
        content = (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode()
        updates.append((settings_path, content))
    baseline = safe_path(directory, ".cairn-nudge/baseline")
    if not baseline.exists():
        count = _save_count(directory / ".cairn" / "events.jsonl")
        updates.append((baseline, f"{count}\n".encode()))
    ignore = ignore_update(directory, (".cairn-nudge/", ".cairn-nudge.log"))
    if ignore is not None:
        updates.append(ignore)
    return updates


def _apply_updates(updates: list[tuple[Path, bytes]]) -> bool:
    changed = False
    for path, content in updates:
        if write_if_changed(path, content):
            changed = True
    return changed


def install_hook(harness: str, directory: Path) -> bool:
    """Instala el hook medido y devuelve si cambió alguno de sus artefactos."""
    return _apply_updates(_hook_updates(harness, directory))


def _nested(keys, value, base):
    node = dict(base)
    cursor = node
    for key in keys[:-1]:
        cursor[key] = {}
        cursor = cursor[key]
    cursor[keys[-1]] = value
    return node


def _config_update(path: Path, keys, server, base) -> bytes | None:
    """Conserva el resto del fichero: solo toca la clave del servidor."""
    if path.exists():
        try:
            # utf-8-sig: un BOM (Windows) no es "JSON no estricto".
            data = json.loads(path.read_text(encoding="utf-8-sig"))
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
        return None
    node[keys[-1]] = server
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


def _snippet_update(path: Path) -> bytes | None:
    block = f"{BEGIN}\n{SNIPPET}\n{END}\n"
    if not path.exists():
        return block.encode()
    # LF siempre: el fichero de instrucciones se commitea y el bloque es LF.
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    stop = text.find(END)
    start = text.rfind(BEGIN, 0, stop) if stop != -1 else -1
    if start != -1:
        updated = text[:start] + block + text[stop + len(END) + 1 :]
    else:
        updated = text.rstrip("\n") + "\n\n" + block
    return updated.encode() if updated != text else None


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


def _remove_snippet_update(path: Path) -> bytes | None:
    """Quita el bloque de cairn y restaura el fichero a como estaba."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    stop = text.find(END)
    start = text.rfind(BEGIN, 0, stop) if stop != -1 else -1
    if start == -1:
        return None
    updated = text[:start].rstrip("\n") + "\n" + text[stop + len(END) + 1 :]
    return updated.encode()


def setup(harness: str, directory: Path) -> list[str]:
    spec = HARNESSES[harness]
    config = safe_path(directory, spec["config"])
    instructions = safe_path(directory, spec["instructions"])
    hook_updates = _hook_updates(harness, directory)
    config_content = _config_update(
        config, spec["config_path"], spec["server"], spec["base"]
    )
    imports_agents = spec["instructions"] != "AGENTS.md" and _imports_agents(instructions)
    snippet_content = (
        _remove_snippet_update(instructions)
        if imports_agents
        else _snippet_update(instructions)
    )
    config_changed = config_content is not None and write_if_changed(config, config_content)
    snippet_changed = snippet_content is not None and write_if_changed(
        instructions, snippet_content
    )
    if imports_agents:
        state = (
            t("duplicate block removed", "bloque duplicado eliminado")
            if snippet_changed
            else t("already there", "ya estaba")
        )
        snippet_line = t(
            f"instructions: {instructions} (imports @AGENTS.md; {state})",
            f"instrucciones: {instructions} (importa @AGENTS.md; {state})",
        )
    else:
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
    hook_state = (
        t("updated", "actualizado")
        if _apply_updates(hook_updates)
        else t("already there", "ya estaba")
    )
    lines.append(f"hook: {safe_path(directory, spec['hook'])} ({hook_state})")
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
