"""Resúmenes de sesión: `sessions.jsonl` append-only, fuera de la memoria curada."""

import json
import os
import secrets
import time
from pathlib import Path

from cairn_mem.jsonl import append_jsonl
from cairn_mem.store import reject_secrets

MAX_SUMMARY = 20000


class Sessions:
    def __init__(self, root: str):
        self.path = Path(root) / "sessions.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, summary: str, id=None, ts=None) -> str:
        summary = self.validate(summary)
        sid = id or secrets.token_hex(6)
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
        record = self._records().get(id)
        return record[1] if record else None

    def last(self):
        """Último recap escrito, leyendo solo la cola. `context` se llama al
        empezar cada sesión, así que no debe parsear el fichero entero."""
        if not self.path.exists():
            return None
        window = 64 * 1024  # MAX_SUMMARY (20000) siempre cabe en una ventana
        with self.path.open("rb") as f:
            end = f.seek(0, os.SEEK_END)
            while end > 0:
                start = max(0, end - window)
                f.seek(start)
                lines = f.read(end - start).split(b"\n")
                if start > 0:
                    lines = lines[1:]  # la primera puede venir partida
                for raw in reversed(lines):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue  # cola rasgada por un crash
                    if event.get("op") == "session" and event.get("id"):
                        return event
                end = start
        return None

    def all(self, limit: int | None = None) -> list[dict]:
        records = sorted(
            self._records().values(),
            key=lambda item: (item[1].get("ts", 0), item[0]),
            reverse=True,
        )
        ordered = [record for _, record in records]
        return ordered[:limit] if limit is not None else ordered

    def _records(self) -> dict[str, tuple[int, dict]]:
        if not self.path.exists():
            return {}
        lines = self.path.read_text(encoding="utf-8-sig").splitlines()
        last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
        records = {}
        for number, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                if number == last:
                    continue  # escritura rasgada por un crash
                raise
            if event.get("op") == "session" and event.get("id"):
                # El nº de línea desempata: dos recaps en el mismo ns siguen el orden
                # del append en vez de un id aleatorio.
                records[event["id"]] = (number, event)
        return records
