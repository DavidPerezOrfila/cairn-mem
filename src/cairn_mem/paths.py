"""Resolución del directorio de datos (.cairn/), compartida por CLI y MCP."""

import os
from pathlib import Path

# Lo que `init` marca como ignorado en `.cairn/`. El `.bak` de `purge` lleva el
# secreto dentro; `*.lock` es el sidecar del append entre procesos.
GITIGNORE_ENTRIES = (
    "cairn.db",
    "cairn.db-*",
    "MEMORY.md",
    ".MEMORY.md.*",
    "sessions.jsonl",
    "events.jsonl.bak",
    "*.lock",
)


def ignore_sessions(root) -> None:
    """`init` ignora `sessions.jsonl`, pero el scope personal no pasa por init y
    el MCP escribe recaps sin el CLI."""
    path = Path(root) / ".gitignore"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    )
    if "sessions.jsonl" in lines:
        return
    path.write_text(
        "\n".join([*lines, "sessions.jsonl"]) + "\n", encoding="utf-8", newline="\n"
    )


def data_dir() -> Path:
    env = os.environ.get("CAIRN_DIR")
    if env:
        return Path(env)
    cwd = Path.cwd().resolve()
    # ~/.cairn (o CAIRN_HOME) es el scope personal: nunca cuenta como raíz de proyecto.
    personal = {
        personal_dir().resolve(),
        (Path.home() / ".cairn").resolve(),
    }
    for folder in (cwd, *cwd.parents):
        candidate = folder / ".cairn"
        if candidate.is_dir() and candidate.resolve() not in personal:
            return candidate
    raise FileNotFoundError("no .cairn/ found in this tree; run 'cairn init'")


def personal_dir() -> Path:
    env = os.environ.get("CAIRN_HOME")
    return Path(env) if env else Path.home() / ".cairn"
