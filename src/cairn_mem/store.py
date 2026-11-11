"""Store: events.jsonl (verdad) + SQLite FTS5 (derivado)."""

import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from itertools import zip_longest
from pathlib import Path

from cairn_mem.anchor import is_stale
from cairn_mem.jsonl import append_jsonl
from cairn_mem.render import KIND_PRIORITY, MAX_TOPIC, render_l0

SCHEMA_VERSION = 3
KINDS = tuple(KIND_PRIORITY)
MAX_BODY = 500
MAX_TITLE = 200
ID_PATTERN = re.compile(r"[0-9a-f]{12}")

SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(
        r"(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-|sk-proj-|sk-ant-|AIza)"
        r"[A-Za-z0-9_-]{8,}"
    ),
    re.compile(
        r"(?i)(?<![a-z0-9])"
        r"(password|passwd|secret|token|api[-_]?key|access[-_]?key|private_key"
        r"|secret[-_]?key|auth[-_]?token)"
        r"(?![a-z0-9])[\"']?\s*[:=]\s*[\"']?\S+"
    ),
    re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
)

MAX_TS = 2**63 - 1  # SQLite INTEGER es signed 64-bit

# Palabras sin contenido: no deben exigir quórum ni decidir la abstención.
STOPWORDS = frozenset(
    {
        "a",
        "al",
        "algo",
        "an",
        "and",
        "ante",
        "antes",
        "are",
        "as",
        "at",
        "be",
        "by",
        "como",
        "con",
        "contra",
        "cual",
        "cuando",
        "cómo",
        "cuál",
        "cuándo",
        "de",
        "del",
        "desde",
        "donde",
        "dónde",
        "el",
        "ella",
        "en",
        "entre",
        "era",
        "es",
        "esa",
        "ese",
        "eso",
        "esta",
        "este",
        "esto",
        "for",
        "from",
        "fue",
        "ha",
        "hasta",
        "hay",
        "how",
        "in",
        "is",
        "it",
        "la",
        "las",
        "le",
        "les",
        "lo",
        "los",
        "mas",
        "me",
        "mi",
        "muy",
        "más",
        "no",
        "nos",
        "o",
        "of",
        "on",
        "or",
        "otra",
        "otro",
        "para",
        "pero",
        "poco",
        "por",
        "que",
        "qué",
        "quien",
        "quién",
        "se",
        "ser",
        "si",
        "sin",
        "sobre",
        "son",
        "su",
        "sus",
        "te",
        "that",
        "the",
        "this",
        "tiene",
        "to",
        "tu",
        "un",
        "una",
        "uno",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "y",
        "ya",
    }
)


def _singular(term: str) -> str:
    """Recorta el plural solo si la raíz conserva 5 caracteres. Con 4, `redis`
    pasaba a `redi` y encontraba `redirect_uri`: un falso positivo peor que el
    plural sin recortar."""
    lowered = term.lower()
    if len(term) >= 7 and lowered.endswith("es"):
        return term[:-2]
    if len(term) >= 6 and lowered.endswith("s"):
        return term[:-1]
    return term


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
CREATE INDEX IF NOT EXISTS ix_mem_active_kind_ts
  ON mem(kind, ts DESC, id) WHERE status = 'active';
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(
  title, body, why, topic_key, anchor_path, content='mem', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON mem BEGIN
  INSERT INTO mem_fts(rowid, title, body, why, topic_key, anchor_path)
  VALUES (new.rowid, new.title, new.body, new.why, new.topic_key, new.anchor_path);
END;
CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON mem BEGIN
  INSERT INTO mem_fts(mem_fts, rowid, title, body, why, topic_key, anchor_path)
  VALUES ('delete', old.rowid, old.title, old.body, old.why, old.topic_key, old.anchor_path);
END;
CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON mem BEGIN
  INSERT INTO mem_fts(mem_fts, rowid, title, body, why, topic_key, anchor_path)
  VALUES ('delete', old.rowid, old.title, old.body, old.why, old.topic_key, old.anchor_path);
  INSERT INTO mem_fts(rowid, title, body, why, topic_key, anchor_path)
  VALUES (new.rowid, new.title, new.body, new.why, new.topic_key, new.anchor_path);
END;
"""


def reject_secrets(*texts):
    for text in texts:
        if text and any(p.search(text) for p in SECRET_PATTERNS):
            raise ValueError("el texto parece contener un secreto; reescríbelo sin él")


def validate_topic(topic_key):
    """Normaliza el topic y rechaza lo que rompería el L0: líneas inyectadas por
    un salto de línea o un topic tan largo que deja el título fuera del presupuesto."""
    if topic_key is None:
        return None
    topic_key = str(topic_key)
    if any(ord(char) < 32 or ord(char) == 127 for char in topic_key):
        raise ValueError("topic_key no puede contener saltos de línea ni controles")
    topic_key = topic_key.strip()
    if len(topic_key) > MAX_TOPIC:
        raise ValueError(f"topic_key supera {MAX_TOPIC} caracteres")
    return topic_key or None


def parse_event(line: str, number: int) -> dict:
    """Valida una línea del JSONL antes de aplicarla. Un evento inventado o
    incompleto debe fallar nombrando el fichero y la línea, no con un KeyError
    ni con un IntegrityError del CHECK de SQLite."""
    where = f"events.jsonl línea {number + 1}"
    try:
        event = json.loads(line)
    except json.JSONDecodeError as error:
        raise ValueError(f"{where}: JSON inválido") from error
    if not isinstance(event, dict) or event.get("op") not in ("save", "archive"):
        raise ValueError(f"{where}: evento sin 'op' save/archive")
    mid = event.get("id")
    if not isinstance(mid, str) or ID_PATTERN.fullmatch(mid) is None:
        raise ValueError(f"{where}: id inválido")
    try:
        int(event.get("ts", 0))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{where}: ts inválido") from error
    for key in ("why", "topic_key", "anchor_path", "anchor_hash"):
        value = event.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{where}: {key} inválido")
    if event["op"] == "save":
        if event.get("kind") not in KINDS:
            raise ValueError(f"{where}: kind inválido")
        title, body = event.get("title"), event.get("body")
        if not isinstance(title, str) or len(title) > MAX_TITLE:
            raise ValueError(f"{where}: title inválido o supera {MAX_TITLE}")
        if not isinstance(body, str) or len(body) > MAX_BODY:
            raise ValueError(f"{where}: body inválido o supera {MAX_BODY}")
    return event


def fingerprint(path: Path) -> tuple[str, str]:
    """Huella barata del JSONL. Un fichero vacío no tiene contenido que comparar."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return ("0", "0")
    if stat.st_size == 0:
        return ("0", "0")
    return (str(stat.st_size), str(stat.st_mtime_ns))


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
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            # El esquema es derivado: se tira y el rebuild lo repone desde el JSONL.
            # La versión 0 es una DB nueva: otro Store puede estar creándola ahora
            # mismo y tirar sus tablas rompería el save concurrente.
            self._conn.executescript(
                "DROP TABLE IF EXISTS mem_fts;"
                "DROP TABLE IF EXISTS mem;"
                "DROP TABLE IF EXISTS meta;"
            )
        self._conn.executescript(DDL)
        self._syncing = False
        if (
            version != SCHEMA_VERSION
            or self._fingerprint() != self._stored_fingerprint()
        ):
            self.rebuild()

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
        title = " ".join(str(title).split())
        if not title:
            raise ValueError("el título está vacío")
        if len(title) > MAX_TITLE:
            raise ValueError(f"title supera {MAX_TITLE} caracteres")
        if len(body) > MAX_BODY:
            raise ValueError(
                f"body supera {MAX_BODY} caracteres; divídelo en dos memorias"
            )
        topic_key = validate_topic(topic_key)
        mid = id or secrets.token_hex(6)
        if ID_PATTERN.fullmatch(mid) is None:
            raise ValueError("id debe ser 12 caracteres hex en minúscula")
        reject_secrets(title, body, why, topic_key, anchor_path)
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
        self._sync()  # aplica primero la cola ajena: evita el rebuild completo
        fingerprint, unseen = self._append(event)
        if unseen:
            self.rebuild()  # llegaron eventos externos: reaplica todo
        else:
            with self._conn:
                self._apply(event)
            if not self._remember_fingerprint(fingerprint, int(fingerprint[0])):
                self.rebuild()  # el fichero cambió mientras se certificaba
            else:
                self.write_l0()
        return mid

    def archive(self, id: str) -> None:
        # El archive debe ordenarse después del save al reconstruir: un save con
        # `ts` futuro (importado) quedaría activo si el archive llevara su ts normal.
        memory = self.get(id)
        ts = time.time_ns()
        if memory is not None:
            ts = min(max(ts, int(memory["ts"]) + 1), MAX_TS)
        event = {"op": "archive", "id": id, "ts": ts}
        fingerprint, unseen = self._append(event)
        if unseen:
            self.rebuild()
        else:
            with self._conn:
                self._apply(event)
            if not self._remember_fingerprint(fingerprint, int(fingerprint[0])):
                self.rebuild()
            else:
                self.write_l0()

    # --- lectura ---

    def active_ordered(self, limit: int = 200) -> list[dict]:
        """Activas en round-robin por kind (prioridad dentro de cada vuelta) y
        ts desc dentro de cada kind. Así un kind con muchas entradas no expulsa
        a los demás del L0. `limit` acota las filas devueltas: 200 líneas ya
        superan el presupuesto de 3000 caracteres."""
        self._sync()
        queues = [
            self._conn.execute(
                "SELECT * FROM mem WHERE status = 'active' AND kind = ? "
                "ORDER BY ts DESC, id LIMIT ?",
                (kind, limit),
            ).fetchall()
            for kind in KIND_PRIORITY
        ]
        rows = [
            dict(row)
            for group in zip_longest(*queues)
            for row in group
            if row is not None
        ]
        return rows[:limit]

    def get(self, id: str):
        self._sync()
        row = self._conn.execute("SELECT * FROM mem WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None

    def search(self, query: str, limit: int = 5) -> list[dict]:
        self._sync()
        limit = max(0, limit)
        terms = self._stems(query)
        if not terms:
            return []
        rows = self._search(self._match(terms, "AND"), limit)
        if not rows and len(terms) > 1:
            # Sin quórum: exigir 2 raíces hundía el parafraseo (S6.1).
            rows = self._search(self._match(terms, "OR"), limit)
        root = self.root.parent
        for row in rows:
            row["stale"] = is_stale(row["anchor_path"], row["anchor_hash"], root)
        return rows

    def dump(self) -> list[dict]:
        self._sync()
        rows = self._conn.execute("SELECT * FROM mem ORDER BY ts, id").fetchall()
        return [dict(r) for r in rows]

    def write_l0(self) -> str:
        """Regenera MEMORY.md de forma atómica y devuelve su contenido."""
        text = render_l0(self)
        tmp = self.root / f".MEMORY.md.{secrets.token_hex(4)}"
        tmp.write_text(text, encoding="utf-8", newline="\n")
        try:
            os.replace(tmp, self.root / "MEMORY.md")
        except OSError as error:
            # Windows: otro proceso (editor/antivirus) tiene MEMORY.md abierto.
            # Es derivado: se regenera en el próximo save, pero el usuario debe saberlo.
            tmp.unlink(missing_ok=True)
            print(f"cairn: no se pudo actualizar MEMORY.md: {error}", file=sys.stderr)
        return text

    # --- rebuild ---

    def rebuild(self) -> None:
        # Huella capturada antes de leer: si otro proceso escribe a mitad, esta
        # huella queda vieja y la siguiente lectura vuelve a reconstruir. Si se
        # guardara la huella final, se certificarían eventos que no se aplicaron.
        fingerprint = self._fingerprint()
        events = []
        raw = self.events.read_bytes() if self.events.exists() else b""
        if raw:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise ValueError("events.jsonl no es UTF-8 válido") from error
            lines = text.splitlines()
            last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
            # Solo un write interrumpido (sin '\n' final) se tolera: un evento
            # inventado con JSON válido sigue fallando, como manda S5.
            torn_tail = not raw.endswith(b"\n")
            for number, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    event = parse_event(line, number)
                except ValueError:
                    if number == last and torn_tail:
                        continue  # escritura rasgada por un crash
                    raise
                events.append((min(int(event.get("ts", 0)), MAX_TS), number, event))
        events.sort(key=lambda item: (item[0], item[1]))
        with self._conn:
            self._conn.execute("DELETE FROM mem")
            for _, _, event in events:
                self._apply(event)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._remember_fingerprint(fingerprint, len(raw), hashlib.sha1(raw).hexdigest())
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

    def _sync(self) -> None:
        """El MCP mantiene el Store abierto: reaplica si el JSONL cambió por fuera
        (git pull, CLI). Sin esto, una lectura serviría datos viejos.
        `_syncing` corta un rebuild anidado si otro proceso escribe a mitad."""
        if self._syncing:
            return
        fingerprint = self._fingerprint()
        if fingerprint == self._stored_fingerprint():
            return
        self._syncing = True
        try:
            self._catch_up(fingerprint)
        finally:
            self._syncing = False

    def _catch_up(self, fingerprint: tuple[str, str]) -> None:
        """Aplica solo la cola nueva. El rebuild completo (caro con 10k) queda
        para cuando no se puede demostrar que el fichero solo creció: truncado,
        replace del mismo tamaño, prefijo distinto, archive o update de un id
        existente (su orden depende del ts global, no del orden de append)."""
        offset, digest = self._progress()
        size = int(fingerprint[0])
        if offset is None or size <= offset or not self._prefix_matches(offset, digest):
            self.rebuild()
            return
        with self.events.open("rb") as f:
            f.seek(offset)
            data = f.read()
        end = data.rfind(b"\n") + 1
        consumed = end
        events = []
        try:
            if end:
                for number, line in enumerate(
                    data[:end].decode("utf-8-sig").splitlines()
                ):
                    if line.strip():
                        events.append(parse_event(line, number))
            tail = data[end:]
            if tail.strip():
                # Línea completa a la que solo le falta el '\n' (otro escritor o
                # un checkout). Certificarla sin aplicarla la perdería para siempre.
                events.append(parse_event(tail.decode("utf-8-sig"), 0))
                consumed = len(data)
        except (UnicodeDecodeError, ValueError):
            self.rebuild()
            return
        ids = [event.get("id") for event in events]
        known = any(
            event.get("op") == "archive"
            or self._conn.execute("SELECT 1 FROM mem WHERE id = ?", (mid,)).fetchone()
            for event, mid in zip(events, ids)
        )
        if known or len(set(ids)) != len(ids):
            self.rebuild()
            return
        if events:
            with self._conn:
                for event in events:
                    self._apply(event)
            self.write_l0()
        if not self._remember_fingerprint(fingerprint, offset + consumed):
            self.rebuild()  # otro proceso cambió el fichero durante el catch-up

    def _append(self, event: dict) -> tuple[tuple[str, str], bool]:
        stored = self._stored_fingerprint()
        start, written, before, fingerprint = append_jsonl(self.events, event)
        # Huella completa, no solo el tamaño: un replace externo del mismo tamaño
        # (git checkout) dejaba la huella vieja y no indexaba lo remoto. Un fichero
        # vacío no tiene contenido que comparar: la mtime es ruido.
        unchanged = (before[0] == "0" and stored[0] == "0") or before == stored
        unseen = not unchanged or int(fingerprint[0]) != start + written
        return fingerprint, unseen

    @staticmethod
    def _match(terms, op):
        return f" {op} ".join(f'"{t}"*' for t in terms)

    @staticmethod
    def _stems(query: str) -> list[str]:
        """Stopwords fuera y plural recortado: el prefijo FTS5 solo crece, así
        que "tokens"* no alcanza "token" y "enlaces"* no alcanza "enlace"."""
        stems = []
        seen = set()
        for term in re.findall(r"\w+", query, re.UNICODE):
            if term.lower() in STOPWORDS:
                continue
            stem = _singular(term)
            if stem.lower() not in seen:
                seen.add(stem.lower())
                stems.append(stem)
        return stems

    def _search(self, match: str, limit: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT m.id, m.kind, m.topic_key, m.title, m.anchor_path, m.anchor_hash,
                      snippet(mem_fts, 1, '', '', '…', 12) AS snippet
               FROM mem_fts JOIN mem m ON m.rowid = mem_fts.rowid
               WHERE mem_fts MATCH ? AND m.status = 'active'
               ORDER BY bm25(mem_fts, 5.0, 1.0, 0.5, 3.0, 2.0), m.rowid LIMIT ?""",
            (match, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def _fingerprint(self) -> tuple[str, str]:
        return fingerprint(self.events)

    def _stored_fingerprint(self) -> tuple[str, str]:
        values = dict(self._conn.execute("SELECT key, value FROM meta").fetchall())
        return (values.get("jsonl_size", ""), values.get("jsonl_mtime_ns", ""))

    def _progress(self) -> tuple[int | None, str | None]:
        values = dict(self._conn.execute("SELECT key, value FROM meta").fetchall())
        offset = values.get("jsonl_offset")
        return (int(offset) if offset is not None else None, values.get("jsonl_hash"))

    def _prefix_matches(self, offset: int, digest: str | None) -> bool:
        """El prefijo aplicado debe ser byte a byte el mismo: un checkout de otra
        rama que además creció no puede colarse como si fuera un append."""
        if digest is None:
            return False
        return self._prefix_hash(offset) == digest

    def _prefix_hash(self, offset: int) -> str:
        hasher = hashlib.sha1()
        if offset:
            with self.events.open("rb") as f:
                remaining = offset
                while remaining:
                    chunk = f.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    hasher.update(chunk)
                    remaining -= len(chunk)
        return hasher.hexdigest()

    def _remember_fingerprint(self, fingerprint=None, offset=None, digest=None) -> bool:
        """Guarda la huella y el prefijo aplicado. `rebuild` pasa el sha1 de los
        bytes que ya leyó; el resto lo recalcula del fichero y devuelve `False`
        si el fichero cambió mientras lo hacía (el prefijo ya no es el aplicado)."""
        size, mtime = fingerprint or self._fingerprint()
        offset = int(size) if offset is None else offset
        if digest is None:
            digest = (
                self._prefix_hash(offset)
                if self.events.exists()
                else hashlib.sha1().hexdigest()
            )
            # Re-stat tras el sha1: un replace ajeno que crezca o cambie de
            # tamaño en esa ventana certificaría bytes que nunca se aplicaron.
            if self._fingerprint() != (str(size), str(mtime)):
                return False
        with self._conn:
            self._conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (
                    ("jsonl_size", size),
                    ("jsonl_mtime_ns", mtime),
                    ("jsonl_offset", str(offset)),
                    ("jsonl_hash", digest),
                ),
            )
        return True


def search_scopes(project, personal, query: str, limit: int = 5) -> list[dict]:
    """Busca en proyecto y scope personal. Un BM25 de otra base no es comparable:
    se entrelazan por posición de ranking, empezando por el proyecto."""
    groups = []
    for scope, store in (("project", project), ("personal", personal)):
        if store is None:
            continue
        rows = store.search(query, limit=limit)
        groups.append([{**row, "scope": scope} for row in rows])
    merged = [row for group in zip_longest(*groups) for row in group if row]
    return merged[: max(0, limit)]
