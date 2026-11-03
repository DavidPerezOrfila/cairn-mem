"""Resúmenes de sesión: `sessions.jsonl` append-only, fuera de la memoria curada."""

import json
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
        return self._records().get(id)

    def all(self, limit: int | None = None) -> list[dict]:
        records = sorted(
            self._records().values(),
            key=lambda record: (record.get("ts", 0), record["id"]),
            reverse=True,
        )
        return records[:limit] if limit is not None else records

    def _records(self) -> dict[str, dict]:
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
                records[event["id"]] = event
        return records
