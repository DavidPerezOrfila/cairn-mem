"""Resolución del directorio de datos (.cairn/), compartida por CLI y MCP."""

import os
from pathlib import Path


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
    raise FileNotFoundError(
        "no se encontró .cairn/ en este árbol; ejecuta 'cairn init'"
    )


def personal_dir() -> Path:
    env = os.environ.get("CAIRN_HOME")
    return Path(env) if env else Path.home() / ".cairn"
