"""Resúmenes de sesión: `sessions.jsonl` append-only, fuera de la memoria curada."""

import json
import os
import secrets
import time
from pathlib import Path

from cairn_mem.jsonl import append_jsonl
from cairn_mem.render import render_l0
from cairn_mem.store import reject_secrets

MAX_SUMMARY = 20000
LAST_SESSION_CHARS = 4000
# Un recap válido se mide en caracteres, pero el fichero en bytes: hasta 4 por
# carácter en UTF-8 y 6 si JSON tiene que escaparlo (`\u0001`). La ventana tiene
# que caber el registro entero, no sus caracteres (20k emojis son 80 KB).
RECORD_WINDOW = MAX_SUMMARY * 6 + 1024


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
        empezar cada sesión, así que no debe parsear el fichero entero. La ventana
        se ensancha cuando el registro más nuevo no cabe en ella: saltárselo
        devolvería un recap viejo como si fuera la última sesión."""
        if not self.path.exists():
            return None
        with self.path.open("rb") as handle:
            end = handle.seek(0, os.SEEK_END)
            window = min(end, RECORD_WINDOW) or 1
            while True:
                start = max(0, end - window)
                handle.seek(start)
                parts = handle.read(end - start).split(b"\n")
                first = 0
                if start > 0:
                    # La primera línea puede venir partida por el corte: solo es
                    # entera si el byte anterior al inicio es un salto de línea.
                    handle.seek(start - 1)
                    if handle.read(1) != b"\n":
                        first = 1
                for raw in reversed(parts[first:]):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue  # cola rasgada por un crash
                    if (
                        isinstance(event, dict)
                        and event.get("op") == "session"
                        and event.get("id")
                    ):
                        return event
                if start == 0:
                    return None
                window = min(end, window * 2)

    def all(self, limit: int | None = None) -> list[dict]:
        if limit is not None and limit < 1:
            # `ordered[:0]` no devuelve nada y un límite negativo corta por el otro
            # extremo: "las últimas 20" devolvería casi todas.
            raise ValueError("limit debe ser 1 o más")
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
            if (
                isinstance(event, dict)
                and event.get("op") == "session"
                and event.get("id")
            ):
                # El nº de línea desempata: dos recaps en el mismo ns siguen el orden
                # del append en vez de un id aleatorio.
                records[event["id"]] = (number, event)
        return records


def context_payload(store) -> dict:
    """L0 y el último recap del proyecto: lo mismo que devuelve la tool `context`."""
    return {"l0": render_l0(store), "last_session": Sessions(str(store.root)).last()}


def context_text(store) -> str:
    """Texto de `context`: L0 más el último recap, recortado a `LAST_SESSION_CHARS`.

    Una sola implementación para el MCP y la CLI: el formato no puede divergir
    entre el arnés que habla JSON-RPC y el que solo tiene una shell.
    """
    payload = context_payload(store)
    record = payload["last_session"]
    if not record:
        return payload["l0"]
    summary = record.get("summary", "")
    if len(summary) > LAST_SESSION_CHARS:
        summary = summary[:LAST_SESSION_CHARS] + "\n… (recortado)"
    return f"{payload['l0']}\n## Última sesión ({record['id']})\n{summary}\n"
