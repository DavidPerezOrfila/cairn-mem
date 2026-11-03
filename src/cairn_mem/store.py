"""Store: events.jsonl (verdad) + SQLite FTS5 (derivado)."""

import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from cairn_mem.anchor import is_stale
from cairn_mem.jsonl import append_jsonl
from cairn_mem.render import KIND_PRIORITY, render_l0

SCHEMA_VERSION = 1
KINDS = ("decision", "convention", "gotcha", "fact")
MAX_BODY = 500

SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"(?i)\b(password|secret|token|api_key)\s*=\s*\S+"),
    re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
)

MAX_TS = 2**63 - 1  # SQLite INTEGER es signed 64-bit

DDL = """
CREATE TABLE IF NOT EXISTS mem (
  id          TEXT PRIMARY KEY,
  ts          INTEGER NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('decision','convention','gotcha','fact')),
  topic_key   TEXT,
  title       TEXT NOT NULL,
  body        TEXT NOT NULL CHECK (length(body) <= 500),
  why         TEXT,
  anchor_path TEXT,
  anchor_hash TEXT,
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','archived'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mem_topic_active
  ON mem(topic_key) WHERE status = 'active' AND topic_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(
  title, body, why, content='mem', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON mem BEGIN
  INSERT INTO mem_fts(rowid, title, body, why) VALUES (new.rowid, new.title, new.body, new.why);
END;
CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON mem BEGIN
  INSERT INTO mem_fts(mem_fts, rowid, title, body, why) VALUES ('delete', old.rowid, old.title, old.body, old.why);
END;
CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON mem BEGIN
  INSERT INTO mem_fts(mem_fts, rowid, title, body, why) VALUES ('delete', old.rowid, old.title, old.body, old.why);
  INSERT INTO mem_fts(rowid, title, body, why) VALUES (new.rowid, new.title, new.body, new.why);
END;
"""


def reject_secrets(*texts):
    for text in texts:
        if text and any(p.search(text) for p in SECRET_PATTERNS):
            raise ValueError("el texto parece contener un secreto; reescríbelo sin él")


class Store:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.events = self.root / "events.jsonl"
        self._conn = sqlite3.connect(str(self.root / "cairn.db"), timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 30000")
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass  # otro Store ya la configuró o lock transitorio
        self._conn.executescript(DDL)
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if (
            version != SCHEMA_VERSION
            or self._fingerprint() != self._stored_fingerprint()
        ):
            self.rebuild()
        self._known_size = int(self._fingerprint()[0])

    # --- escritura ---

    def save(
        self,
        kind,
        title,
        body,
        why=None,
        topic_key=None,
        anchor_path=None,
        anchor_hash=None,
        id=None,
        ts=None,
    ) -> str:
        if kind not in KINDS:
            raise ValueError(f"kind inválido: {kind}")
        if len(body) > MAX_BODY:
            raise ValueError(
                f"body supera {MAX_BODY} caracteres; divídelo en dos memorias"
            )
        reject_secrets(title, body, why, topic_key, anchor_path)
        mid = id or secrets.token_hex(6)
        event = {
            "op": "save",
            "id": mid,
            "ts": time.time_ns() if ts is None else int(ts),
            "kind": kind,
            "title": title,
            "body": body,
        }
        for key, value in (
            ("topic_key", topic_key),
            ("why", why),
            ("anchor_path", anchor_path),
            ("anchor_hash", anchor_hash),
        ):
            if value is not None:
                event[key] = value
        fingerprint, unseen = self._append(event)
        if unseen:
            self.rebuild()  # llegaron eventos externos: reaplica todo
        else:
            with self._conn:
                self._apply(event)
            self._remember_fingerprint(fingerprint)
            self._known_size = int(fingerprint[0])
            self.write_l0()
        return mid

    def archive(self, id: str) -> None:
        event = {"op": "archive", "id": id, "ts": time.time_ns()}
        fingerprint, unseen = self._append(event)
        if unseen:
            self.rebuild()
        else:
            with self._conn:
                self._apply(event)
            self._remember_fingerprint(fingerprint)
            self._known_size = int(fingerprint[0])
            self.write_l0()

    # --- lectura ---

    def active_ordered(self, limit: int = 200) -> list[dict]:
        """Activas en orden L0 (kind y ts desc). `limit` acota el trabajo de render:
        200 líneas ya superan el presupuesto de 3000 caracteres."""
        priority = " ".join(
            f"WHEN '{kind}' THEN {order}" for kind, order in KIND_PRIORITY.items()
        )
        rows = self._conn.execute(
            f"""SELECT * FROM mem WHERE status = 'active'
                ORDER BY CASE kind {priority} END, ts DESC, id LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, id: str):
        row = self._conn.execute("SELECT * FROM mem WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None

    def search(self, query: str, limit: int = 5) -> list[dict]:
        limit = max(0, limit)
        terms = re.findall(r"\w+", query, re.UNICODE)
        if not terms:
            return []
        rows = []
        for op in ("AND", "OR"):
            rows = self._search(self._match(terms, op), limit)
            if rows:
                break
        root = self.root.parent
        for row in rows:
            row["stale"] = is_stale(row["anchor_path"], row["anchor_hash"], root)
        return rows

    def dump(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM mem ORDER BY ts, id").fetchall()
        return [dict(r) for r in rows]

    def write_l0(self) -> str:
        """Regenera MEMORY.md de forma atómica y devuelve su contenido."""
        text = render_l0(self)
        tmp = self.root / f".MEMORY.md.{secrets.token_hex(4)}"
        tmp.write_text(text, encoding="utf-8", newline="\n")
        try:
            os.replace(tmp, self.root / "MEMORY.md")
        except OSError:
            # Windows: otro proceso (editor/antivirus) tiene MEMORY.md abierto.
            # Es derivado: se regenera en el próximo save.
            tmp.unlink(missing_ok=True)
        return text

    # --- rebuild ---

    def rebuild(self) -> None:
        events = []
        if self.events.exists():
            lines = self.events.read_text(encoding="utf-8-sig").splitlines()
            last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
            for number, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    if number == last:
                        continue  # escritura rasgada por un crash
                    raise
                events.append((event.get("ts", 0), number, event))
        events.sort(key=lambda item: (item[0], item[1]))
        with self._conn:
            self._conn.execute("DELETE FROM mem")
            for _, _, event in events:
                self._apply(event)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._remember_fingerprint()
        self._known_size = int(self._fingerprint()[0])
        self.write_l0()

    # --- internos ---

    def _apply(self, event: dict) -> None:
        if event["op"] == "save":
            mid = event["id"]
            ts = min(int(event.get("ts", 0)), MAX_TS)
            topic_key = event.get("topic_key")
            status = "active"
            if topic_key:
                newer = self._conn.execute(
                    "SELECT 1 FROM mem WHERE topic_key = ? AND status = 'active' "
                    "AND id <> ? AND ts > ?",
                    (topic_key, mid, ts),
                ).fetchone()
                if newer:
                    status = "superseded"  # apply fuera de orden: gana el más nuevo
                else:
                    self._conn.execute(
                        "UPDATE mem SET status = 'superseded' "
                        "WHERE topic_key = ? AND status = 'active' AND id <> ?",
                        (topic_key, mid),
                    )
            self._conn.execute(
                """INSERT INTO mem (id, ts, kind, topic_key, title, body, why, anchor_path, anchor_hash, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     ts = excluded.ts, kind = excluded.kind, topic_key = excluded.topic_key,
                     title = excluded.title, body = excluded.body, why = excluded.why,
                     anchor_path = excluded.anchor_path, anchor_hash = excluded.anchor_hash,
                     status = excluded.status""",
                (
                    mid,
                    ts,
                    event["kind"],
                    topic_key,
                    event["title"],
                    event["body"],
                    event.get("why"),
                    event.get("anchor_path"),
                    event.get("anchor_hash"),
                    status,
                ),
            )
        elif event["op"] == "archive":
            self._conn.execute(
                "UPDATE mem SET status = 'archived' WHERE id = ?", (event["id"],)
            )

    def _append(self, event: dict) -> tuple[tuple[str, str], bool]:
        before, written = append_jsonl(self.events, event)
        stat = self.events.stat()
        unseen = before != self._known_size or stat.st_size != before + written
        return (str(stat.st_size), str(stat.st_mtime_ns)), unseen

    @staticmethod
    def _match(terms, op):
        return f" {op} ".join(f'"{t}"*' for t in terms)

    def _search(self, match: str, limit: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT m.id, m.kind, m.title, m.anchor_path, m.anchor_hash,
                      snippet(mem_fts, 1, '', '', '…', 12) AS snippet
               FROM mem_fts JOIN mem m ON m.rowid = mem_fts.rowid
               WHERE mem_fts MATCH ? AND m.status = 'active'
               ORDER BY bm25(mem_fts, 5.0, 1.0, 0.5) LIMIT ?""",
            (match, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def _fingerprint(self) -> tuple[str, str]:
        try:
            stat = self.events.stat()
        except FileNotFoundError:
            return ("0", "0")
        return (str(stat.st_size), str(stat.st_mtime_ns))

    def _stored_fingerprint(self) -> tuple[str, str]:
        values = dict(self._conn.execute("SELECT key, value FROM meta").fetchall())
        return (values.get("jsonl_size", ""), values.get("jsonl_mtime_ns", ""))

    def _remember_fingerprint(self, fingerprint=None) -> None:
        size, mtime = fingerprint or self._fingerprint()
        with self._conn:
            self._conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (("jsonl_size", size), ("jsonl_mtime_ns", mtime)),
            )
