"""Importador de otra herramienta: SQLite ajena -> events.jsonl / sessions.jsonl."""

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cairn_mem.paths import data_dir, personal_dir
from cairn_mem.sessions import Sessions
from cairn_mem.store import MAX_TITLE, Store, reject_secrets

KIND_BY_TYPE = {
    "decision": "decision",
    "architecture": "decision",
    "config": "decision",
    "pattern": "convention",
    "convention": "convention",
    "discovery": "gotcha",
    "bugfix": "gotcha",
    "gotcha": "gotcha",
    "fact": "fact",
    "preference": "fact",
}

SECTION = re.compile(
    r"(?m)^\*{0,2}(What|Why|Where|Learned)\*{0,2}\s*:\s*", re.IGNORECASE
)

# Sal fija: cambiarla duplicaría todo lo importado con 0.2.0.
ID_SALT = "engram"


def import_legacy(db_path, dry_run=False) -> dict:
    db = Path(db_path)
    if not db.is_file():
        raise FileNotFoundError(f"no existe la base de datos: {db}")
    report = {
        "memories": 0,
        "sessions": 0,
        "skipped": 0,
        "foreign": 0,
        "rejected": 0,
        "dry_run": dry_run,
    }
    project = {"resolved": False, "root": None, "store": None, "sessions": None}

    def project_root():
        """Raíz del repo actual o None si no hay `.cairn/`: el import puede ser
        solo de filas globales desde una carpeta sin proyecto."""
        if not project["resolved"]:
            project["resolved"] = True
            try:
                project["root"] = data_dir().parent
            except FileNotFoundError:
                project["root"] = None
        return project["root"]

    def project_store():
        if project["store"] is None:
            project["store"] = Store(str(data_dir()))
        return project["store"]

    def project_sessions():
        if project["sessions"] is None:
            project["sessions"] = Sessions(str(data_dir()))
        return project["sessions"]

    personal = None if dry_run else Store(str(personal_dir()))
    personal_sessions = None if dry_run else Sessions(str(personal_dir()))

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT o.*, p.directory AS directory
        FROM observations o
        LEFT JOIN capture_project_provenance p
          ON p.entity_kind = 'observation' AND p.entity_id = CAST(o.id AS TEXT)
        WHERE o.deleted_at IS NULL AND o.superseded_by_sync_id IS NULL
        ORDER BY o.created_at, o.id
        """
    ).fetchall()
    conn.close()

    for row in rows:
        if row["type"] == "session_summary":
            if row["scope"] in ("global", "personal"):
                target = personal_sessions
            elif _belongs(row, project_root()):
                target = None if dry_run else project_sessions()
            else:
                report["foreign"] += 1
                continue
            summary = row["content"] or ""
            if dry_run:
                try:
                    Sessions.validate(summary)
                except ValueError:
                    report["rejected"] += 1
                    continue
            sid = _id(row["id"])
            if not dry_run and target.get(sid):
                report["skipped"] += 1
                continue
            if not dry_run:
                try:
                    target.save(summary, id=sid, ts=_ts(row["created_at"]))
                except ValueError:
                    report["rejected"] += 1
                    continue
            report["sessions"] += 1
            continue

        if row["scope"] in ("global", "personal"):
            store = personal
            topic = f"{row['project']}/{row['topic_key']}" if row["topic_key"] else None
        elif _belongs(row, project_root()):
            store = None if dry_run else project_store()
            topic = row["topic_key"]
        else:
            report["foreign"] += 1
            continue

        mid = _id(row["id"])
        if not dry_run and store.get(mid):
            report["skipped"] += 1
            continue
        body, why = _split(row["content"])
        # Título vacío o larguísimo no debe perder la memoria migrada.
        title = (row["title"] or "").strip() or body[:MAX_TITLE] or "sin título"
        title = title[:MAX_TITLE]
        if dry_run:
            try:
                reject_secrets(title, body, why, topic)
            except ValueError:
                report["rejected"] += 1
                continue
        else:
            try:
                store.save(
                    kind=KIND_BY_TYPE.get(row["type"], "fact"),
                    title=title,
                    body=body,
                    why=why,
                    topic_key=topic,
                    id=mid,
                    ts=_ts(row["created_at"]),
                )
            except ValueError:
                report["rejected"] += 1
                continue
        report["memories"] += 1
    return report


def _belongs(row, root) -> bool:
    """La observación es del repo actual: por provenance o por nombre de proyecto."""
    if root is None:
        return False
    directory = row["directory"]
    if directory:
        return os.path.normcase(os.path.abspath(directory)) == os.path.normcase(
            str(root)
        )
    return (row["project"] or "") == root.name


def _id(value) -> str:
    return hashlib.sha1(f"{ID_SALT}:{value}".encode()).hexdigest()[:12]


def _ts(value):
    if not value:
        return None
    text = str(value).strip()
    match = re.match(r"^(.*?)\.(\d+)(.*)$", text)
    if match:
        # fromisoformat de 3.10 solo acepta 3 o 6 dígitos decimales.
        text = f"{match.group(1)}.{match.group(2)[:6]:0<6}{match.group(3)}"
    text = text.replace("Z", "+00:00")
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1_000_000_000)


def _split(content: str) -> tuple[str, str]:
    """`What` -> body; `Why/Where/Learned` -> why. Sin secciones: todo a body."""
    content = (content or "").strip()
    matches = list(SECTION.finditer(content))
    if not matches:
        return content[:500], None
    sections = {}
    for position, match in enumerate(matches):
        end = (
            matches[position + 1].start()
            if position + 1 < len(matches)
            else len(content)
        )
        sections[match.group(1).lower()] = content[match.end() : end].strip()
    body = sections.pop("what", "") or content
    why = (
        " | ".join(
            f"{name.capitalize()}: {text}" for name, text in sections.items() if text
        )
        or None
    )
    return body[:500].strip(), why
