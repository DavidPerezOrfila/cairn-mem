"""Append de una línea JSON con una sola `os.write`."""

import json
import os
import threading
from pathlib import Path

# El O_APPEND de Windows no es atómico entre hilos: serializa dentro del proceso.
_LOCK = threading.Lock()


def append_jsonl(path: Path, event: dict) -> tuple[int, int]:
    """Añade `event` y devuelve (tamaño previo, bytes escritos)."""
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    data = line.encode("utf-8")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
    with _LOCK:
        before = path.stat().st_size if path.exists() else 0
        fd = os.open(path, flags, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    return before, len(data)
