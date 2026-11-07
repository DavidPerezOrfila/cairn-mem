"""Append de una línea JSON con una sola `os.write`."""

import json
import os
import threading
from pathlib import Path

# El O_APPEND de Windows no es atómico entre hilos: serializa dentro del proceso.
_LOCK = threading.Lock()
TAIL_CHUNK = 8192
MAX_FRAGMENT = 64 * 1024


def append_jsonl(
    path: Path, event: dict
) -> tuple[int, int, tuple[str, str], tuple[str, str]]:
    """Repara una cola rasgada, añade `event` y devuelve
    (offset de escritura, bytes escritos, huella previa, huella posterior)."""
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    data = line.encode("utf-8")
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
    with _LOCK:
        fd = os.open(path, flags, 0o644)
        try:
            stat = os.fstat(fd)
            before = (str(stat.st_size), str(stat.st_mtime_ns))
            start = _repair_tail(fd, stat.st_size)
            try:
                written = os.write(fd, data)
            except OSError:
                # Disco lleno: el write puede fallar a medias.
                os.ftruncate(fd, start)
                raise
            if written != len(data):
                # Un solo escritor por proyecto (diseño): el truncado no pisa
                # líneas ajenas. Deshace la línea a medias.
                os.ftruncate(fd, start)
                raise OSError(f"escritura incompleta: {written}/{len(data)} bytes")
        finally:
            os.close(fd)
        stat = path.stat()
    return start, len(data), before, (str(stat.st_size), str(stat.st_mtime_ns))


def _repair_tail(fd: int, size: int) -> int:
    """Si el fichero no acaba en `\\n` (crash a mitad de write), deja una cola
    válida y devuelve el offset donde debe empezar el siguiente evento. Un
    append detrás de un fragmento inválido rompería el rebuild con el JSON
    corrupto en una línea intermedia."""
    if size == 0:
        return 0
    os.lseek(fd, size - 1, os.SEEK_SET)
    if os.read(fd, 1) == b"\n":
        return size
    start = 0
    position = size
    while position > 0:
        step = min(TAIL_CHUNK, position)
        position -= step
        os.lseek(fd, position, os.SEEK_SET)
        chunk = os.read(fd, step)
        index = chunk.rfind(b"\n")
        if index != -1:
            start = position + index + 1
            break
    if size - start > MAX_FRAGMENT:
        os.ftruncate(fd, start)
        return start
    os.lseek(fd, start, os.SEEK_SET)
    fragment = os.read(fd, size - start)
    try:
        parsed = json.loads(fragment.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict):
        os.ftruncate(fd, start)
        return start
    # Línea completa a la que solo le faltó el '\n' final: se conserva.
    if os.write(fd, b"\n") != 1:
        raise OSError("no se pudo reparar la cola del JSONL")
    return size + 1
