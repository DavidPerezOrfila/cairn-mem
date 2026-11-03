"""Append de una línea JSON con una sola `os.write`."""

import json
import os
import threading
from pathlib import Path

# El O_APPEND de Windows no es atómico entre hilos: serializa dentro del proceso.
_LOCK = threading.Lock()


def append_jsonl(path: Path, event: dict) -> tuple[int, int, tuple[str, str]]:
    """Añade `event` y devuelve (tamaño previo, bytes escritos, huella posterior)."""
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    data = line.encode("utf-8")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
    with _LOCK:
        before = path.stat().st_size if path.exists() else 0
        fd = os.open(path, flags, 0o644)
        try:
            try:
                written = os.write(fd, data)
            except OSError:
                # Disco lleno: el write puede fallar a medias.
                os.ftruncate(fd, before)
                raise
            if written != len(data):
                # Un solo escritor por proyecto (diseño): el truncado no pisa
                # líneas ajenas. Deshace la línea a medias.
                os.ftruncate(fd, before)
                raise OSError(f"escritura incompleta: {written}/{len(data)} bytes")
        finally:
            os.close(fd)
        stat = path.stat()
    return before, len(data), (str(stat.st_size), str(stat.st_mtime_ns))
