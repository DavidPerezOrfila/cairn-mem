"""cairn doctor: diagnóstico local del store y de la instalación.

No sale a la red. Los ficheros derivados (`cairn.db`, `MEMORY.md`) se refrescan como en
cualquier otro comando; el JSONL no se toca.
"""

import os
import sqlite3
import sys
from pathlib import Path

from cairn_mem.anchor import is_stale
from cairn_mem.sessions import Sessions
from cairn_mem.store import SCHEMA_VERSION, Store, fingerprint, parse_event

MAX_L0 = 3000
# `events.jsonl` depende de `--share`: init lo ignora en modo local y lo versiona en share.
GITIGNORE_ENTRIES = ("MEMORY.md", "cairn.db", ".MEMORY.md.*", "sessions.jsonl")


def _check(status: str, name: str, detail: str) -> dict:
    return {"status": status, "check": name, "detail": detail}


def _python() -> dict:
    return _check("ok", "python", f"{sys.version.split()[0]} ({sys.executable})")


def _sqlite() -> dict:
    try:
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE VIRTUAL TABLE probe USING fts5(x)")
    except sqlite3.OperationalError as error:
        return _check("fail", "sqlite", f"FTS5 no disponible: {error}")
    return _check("ok", "sqlite", f"FTS5 disponible (SQLite {sqlite3.sqlite_version})")


def installations(path_env: str | None = None) -> list[str]:
    """Carpetas de PATH que exponen `cairn` o `cairn-mem`.

    `shutil.which` devuelve solo la primera coincidencia; aquí interesan todas para
    detectar el caso de dos instalaciones (editable + pipx/uv) con versiones distintas.
    """
    env = os.environ.get("PATH", "") if path_env is None else path_env
    names = ("cairn", "cairn-mem")
    suffixes = ("", ".exe", ".cmd", ".bat")
    folders = set()
    for folder in env.split(os.pathsep):
        if not folder:
            continue
        if any(
            (Path(folder) / f"{name}{suffix}").is_file()
            for name in names
            for suffix in suffixes
        ):
            folders.add(str(Path(folder)))
    return sorted(folders)


def _install() -> dict:
    folders = installations()
    if not folders:
        return _check("warn", "install", "no está en PATH")
    if len(folders) > 1:
        return _check(
            "warn",
            "install",
            f"{len(folders)} instalaciones: {'; '.join(folders)}",
        )
    return _check("ok", "install", folders[0])


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _gitignore(root: Path) -> dict:
    path = root / ".gitignore"
    if not path.exists():
        return _check("warn", "gitignore", "no existe: ejecuta cairn init")
    text = _read_text(path)
    if text is None:
        return _check("fail", "gitignore", "no se pudo leer (¿no es UTF-8?)")
    lines = set(text.splitlines())
    missing = [entry for entry in GITIGNORE_ENTRIES if entry not in lines]
    if missing:
        return _check("warn", "gitignore", f"faltan {', '.join(missing)}: cairn init")
    return _check("ok", "gitignore", "entradas de cairn presentes")


def _events(root: Path) -> dict:
    path = root / "events.jsonl"
    if not path.exists():
        return _check("warn", "events", "no existe: se crea al guardar")
    try:
        raw = path.read_bytes()
    except OSError as error:
        return _check("fail", "events", f"no se pudo leer: {error}")
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        return _check("fail", "events", "no es UTF-8 válido")
    last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
    torn_tail = bool(raw) and not raw.endswith(b"\n")
    count = 0
    for number, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            parse_event(line, number)
        except ValueError as error:
            if number == last and torn_tail:
                continue  # misma tolerancia que el rebuild
            return _check("fail", "events", str(error))
        count += 1
    return _check("ok", "events", f"{count} eventos")


def _sessions(root: Path) -> dict:
    sessions = Sessions(str(root))
    if not sessions.path.exists():
        return _check("ok", "sessions", "sin fichero (se crea al guardar)")
    try:
        records = sessions.all()
    except ValueError as error:
        return _check("fail", "sessions", str(error))
    except OSError as error:
        return _check("fail", "sessions", f"no se pudo leer: {error}")
    return _check("ok", "sessions", f"{len(records)} recaps")


def _db(root: Path) -> dict:
    path = root / "cairn.db"
    if not path.exists():
        return _check("warn", "db", "no existe: se reconstruye al abrir")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            stored = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error:
        return _check("warn", "db", "ilegible: se reconstruye al abrir")
    if version != SCHEMA_VERSION:
        return _check("warn", "db", f"esquema {version}: se reconstruye al abrir")
    size, mtime = fingerprint(root / "events.jsonl")
    if (stored.get("jsonl_size"), stored.get("jsonl_mtime_ns")) != (size, mtime):
        return _check("warn", "db", "desincronizada: se reconstruye al abrir")
    return _check("ok", "db", "sincronizada")


def _l0(root: Path) -> dict:
    path = root / "MEMORY.md"
    if not path.exists():
        return _check("warn", "l0", "no existe: se genera al abrir")
    text = _read_text(path)
    if text is None:
        return _check("fail", "l0", "no se pudo leer (¿no es UTF-8?)")
    length = len(text)
    status = "ok" if length <= MAX_L0 else "fail"
    return _check(status, "l0", f"{length}/{MAX_L0} caracteres")


def _anchors(store: Store) -> dict:
    active = [row for row in store.dump() if row["status"] == "active"]
    stale = [
        row
        for row in active
        if row["anchor_path"]
        and is_stale(row["anchor_path"], row["anchor_hash"], store.root.parent)
    ]
    if stale:
        return _check("warn", "anchors", f"{len(stale)} stale: cairn check los lista")
    return _check("ok", "anchors", "sin anclas stale")


def run(root: Path | None) -> list[dict]:
    checks = [_python(), _sqlite(), _install()]
    if root is None:
        checks.append(
            _check("fail", "store", "no hay store: ejecuta cairn init o --personal")
        )
        return checks
    checks.append(_check("ok", "store", str(root)))
    checks.append(_gitignore(root))
    checks.append(_events(root))
    checks.append(_sessions(root))
    checks.append(_db(root))
    try:
        store = Store(str(root))
    except (ValueError, sqlite3.DatabaseError) as error:
        checks.append(_check("fail", "index", str(error)))
        return checks
    checks.append(_l0(root))
    checks.append(_anchors(store))
    return checks
