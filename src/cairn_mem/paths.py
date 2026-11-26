"""Resolución del directorio de datos (.cairn/), compartida por CLI y MCP."""

import os
import stat
import tempfile
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


def safe_path(root: str | Path, relative: str) -> Path:
    """Devuelve una ruta gestionada sin enlaces simbólicos ni escapes de la raíz."""
    base = Path(root).resolve()
    if base.exists() and not base.is_dir():
        raise ValueError(f"{base}: expected a directory")
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise ValueError(f"{relative}: expected a relative path inside {base}")
    current = base
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{current}: symbolic links are not allowed")
        if current.exists():
            expected = current.is_dir() if index < len(parts) - 1 else current.is_file()
            if not expected:
                raise ValueError(f"{current}: expected a {'directory' if index < len(parts) - 1 else 'file'}")
        if not current.resolve().is_relative_to(base):
            raise ValueError(f"{current}: path escapes {base}")
    return current


def write_if_changed(path: Path, content: bytes) -> bool:
    """Reemplaza un archivo completo de forma atómica y solo si cambia."""
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def ignore_update(root: str | Path, entries: tuple[str, ...]) -> tuple[Path, bytes] | None:
    """Prepara las entradas nuevas sin escribir; el caller decide cuándo aplicarlas."""
    path = safe_path(root, ".gitignore")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    missing = [entry for entry in entries if entry not in lines]
    if not missing:
        return None
    return path, ("\n".join([*lines, *missing]) + "\n").encode()


def _ignore_entries(root: str | Path, entries: tuple[str, ...]) -> bool:
    update = ignore_update(root, entries)
    return update is not None and write_if_changed(*update)


def ignore_sessions(root: str | Path) -> None:
    """`init` ignora `sessions.jsonl`, pero el scope personal no pasa por init y
    el MCP escribe recaps sin el CLI."""
    _ignore_entries(root, ("sessions.jsonl",))


def ignore_nudge(root: str | Path) -> bool:
    return _ignore_entries(root, (".cairn-nudge/", ".cairn-nudge.log"))


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
