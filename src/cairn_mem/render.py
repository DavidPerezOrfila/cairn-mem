"""L0: MEMORY.md determinista con presupuesto de caracteres."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cairn_mem.anchor import MAX_HASH_BYTES, file_hash, is_stale

KIND_PRIORITY = {"convention": 0, "decision": 1, "gotcha": 2, "fact": 3}
EXCERPT = 120
MAX_TOPIC = 100
TITLE = "# Memoria del proyecto (cairn L0)"
STALE_MARK = " ⚠ revisar"
HASH_WORKERS = 8


def render_l0(store, max_chars: int = 3000, project_root=None) -> str:
    """Orden fijo por kind y ts desc, cortado al presupuesto."""
    root = Path(project_root) if project_root else Path(store.root).parent
    candidates = []
    used = len(TITLE) + 1
    for row in store.active_ordered():
        line = _line(row)
        # Sin marca: las filas candidatas son un superconjunto de las elegidas.
        if used + len(line) + 1 > max_chars:
            break
        candidates.append((row, line))
        used += len(line) + 1
    hashes = _prewarm([row for row, _ in candidates], root)
    lines = [TITLE]
    for row, line in candidates:
        if is_stale(row["anchor_path"], row["anchor_hash"], root, cache=hashes):
            line += STALE_MARK
        if len("\n".join([*lines, line])) + 1 > max_chars:
            break
        lines.append(line)
    return "\n".join(lines) + "\n"


def _prewarm(rows: list[dict], root: Path) -> dict:
    """Hashea en paralelo los anclas de las filas candidatas.

    Un render con decenas de anclas grandes dominaba el coste de `save`; leerlas
    en serie era el cuello. No se guarda entre comandos: el hash solo vale para
    este render (ver `anchor._cached_hash`).
    """
    paths = sorted(
        {str(root / row["anchor_path"]) for row in rows if row["anchor_path"]}
    )
    if len(paths) < 2:
        return {}

    def load(key: str):
        try:
            stat = Path(key).stat()
            if stat.st_size > MAX_HASH_BYTES:
                return None
            return key, (stat.st_size, stat.st_mtime_ns, file_hash(key))
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=min(HASH_WORKERS, len(paths))) as pool:
        return dict(entry for entry in pool.map(load, paths) if entry)


def _line(row: dict) -> str:
    body = " ".join(row["body"].split())[:EXCERPT]
    # Un evento externo puede traer saltos de línea: el L0 no admite líneas inyectadas.
    mid = " ".join(str(row["id"]).split())
    title = " ".join(str(row["title"]).split())
    topic = ""
    if row.get("topic_key"):
        topic = f"[{' '.join(str(row['topic_key']).split())[:MAX_TOPIC]}] "
    return f"- [{mid}] {row['kind']}: {topic}{title} — {body}"
