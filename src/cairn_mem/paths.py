"""Resolución del directorio de datos (.cairn/), compartida por CLI y MCP."""

import os
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("CAIRN_DIR")
    if env:
        return Path(env)
    cwd = Path.cwd().resolve()
    for folder in (cwd, *cwd.parents):
        if (folder / ".cairn").is_dir():
            return folder / ".cairn"
    raise FileNotFoundError(
        "no se encontró .cairn/ en este árbol; ejecuta 'cairn init'"
    )
