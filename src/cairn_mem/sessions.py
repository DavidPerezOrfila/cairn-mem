"""Resúmenes de sesión: `sessions.jsonl` append-only, fuera de la memoria curada."""

import json
import os
import secrets
import time
from pathlib import Path

from cairn_mem.jsonl import append_jsonl
from cairn_mem.store import ID_PATTERN, reject_secrets

MAX_SUMMARY = 20000
WINDOW = 64 * 1024
LONGEST_LINE = 1 << 20  # un recap de MAX_SUMMARY con escapes se queda muy abajo


def _session_record(raw: bytes):
    line = raw.strip()
    if not line:
        return None
    try:
        event = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(event, dict) and event.get("op") == "session" and event.get("id"):
        return event
    return None


def _valid_id(sid: str) -> str:
    if not isinstance(sid, str) or not ID_PATTERN.fullmatch(sid):
        raise ValueError(f"id de sesión inválido: {sid!r}; se esperan 12 hex")
    return sid


class Sessions:
    def __init__(self, root: str):
        self.path = Path(root) / "sessions.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, summary: str, id=None, ts=None) -> str:
        summary = self.validate(summary)
        sid = _valid_id(id) if id is not None else secrets.token_hex(6)
        append_jsonl(
            self.path,
            {
                "op": "session",
                "id": sid,
                "ts": time.time_ns() if ts is None else int(ts),
                "summary": summary,
            },
        )
        return sid

    @staticmethod
    def validate(summary: str) -> str:
        summary = summary.strip()
        if not summary:
            raise ValueError("el resumen está vacío")
        if len(summary) > MAX_SUMMARY:
            raise ValueError(f"el resumen supera {MAX_SUMMARY} caracteres")
        reject_secrets(summary)
        return summary

    def get(self, id: str):
        record = self._records().get(_valid_id(id))
        return record[1] if record else None

    def last(self):
        """Último recap escrito, leyendo solo la cola. `context` se llama al
        empezar cada sesión, así que no debe parsear el fichero entero. La
        ventana se acumula hacia atrás: un recap de 20k con escapes supera los
        64 KB y cabía partido en dos ventanas. Mismo orden que `all`: append."""
        if not self.path.exists():
            return None
        with self.path.open("rb") as f:
            end = f.seek(0, os.SEEK_END)
            buffer = b""
            while end > 0:
                start = max(0, end - WINDOW)
                f.seek(start)
                buffer = f.read(end - start) + buffer
                parts = buffer.split(b"\n")
                complete = parts[1:] if start > 0 else parts
                for raw in reversed(complete):
                    record = _session_record(raw)
                    if record is not None:
                        return record
                buffer = parts[0]
                if len(buffer) > LONGEST_LINE:
                    buffer = b""  # línea corrupta gigante: sigue hacia atrás
                end = start
        return None

    def all(self, limit: int | None = None) -> list[dict]:
        # el nº de línea es el orden del append, el mismo que usa `last`:
        # `ts` no ordena porque un escritor con reloj atrasado lo rompería.
        records = sorted(
            self._records().values(), key=lambda item: item[0], reverse=True
        )
        ordered = [record for _, record in records]
        return ordered[:limit] if limit is not None else ordered

    def _records(self) -> dict[str, tuple[int, dict]]:
        if not self.path.exists():
            return {}
        text = self.path.read_text(encoding="utf-8-sig")
        torn_tail = not text.endswith("\n")
        lines = text.splitlines()
        last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
        records = {}
        for number, line in enumerate(lines):
            if not line.strip():
                continue
            where = f"sessions.jsonl línea {number + 1}"
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                if number == last and torn_tail:
                    continue  # escritura rasgada por un crash
                raise ValueError(f"{where}: JSON inválido") from error
            if not isinstance(event, dict):
                if number == last and torn_tail:
                    continue
                raise ValueError(f"{where}: evento inválido")
            if event.get("op") == "session" and event.get("id"):
                # El nº de línea desempata: dos recaps en el mismo ns siguen el orden
                # del append en vez de un id aleatorio.
                records[event["id"]] = (number, event)
        return records
