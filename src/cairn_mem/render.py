"""L0: MEMORY.md determinista con presupuesto de caracteres."""

from pathlib import Path

from cairn_mem.anchor import is_stale

KIND_PRIORITY = {"convention": 0, "decision": 1, "gotcha": 2, "fact": 3}
EXCERPT = 120
MAX_TOPIC = 100
TITLE = "# Memoria del proyecto (cairn L0)"


def render_l0(store, max_chars: int = 3000, project_root=None) -> str:
    """Orden fijo por kind y ts desc, cortado al presupuesto."""
    root = Path(project_root) if project_root else Path(store.root).parent
    rows = store.active_ordered()
    lines = [TITLE]
    for row in rows:
        line = _line(row, root)
        if len("\n".join([*lines, line])) + 1 > max_chars:
            break
        lines.append(line)
    return "\n".join(lines) + "\n"


def _line(row: dict, root: Path) -> str:
    body = " ".join(row["body"].split())[:EXCERPT]
    # Un evento externo puede traer saltos de línea: el L0 no admite líneas inyectadas.
    mid = " ".join(str(row["id"]).split())
    title = " ".join(str(row["title"]).split())
    topic = ""
    if row.get("topic_key"):
        topic = f"[{' '.join(str(row['topic_key']).split())[:MAX_TOPIC]}] "
    text = f"- [{mid}] {row['kind']}: {topic}{title} — {body}"
    if is_stale(row["anchor_path"], row["anchor_hash"], root):
        text += " ⚠ revisar"
    return text
