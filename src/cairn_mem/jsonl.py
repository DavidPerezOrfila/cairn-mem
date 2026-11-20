"""Append de una línea JSON con una sola `os.write`."""

import json
import os
import sys
import threading
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# El O_APPEND de Windows no es atómico entre hilos: serializa dentro del proceso.
_LOCK = threading.Lock()
TAIL_CHUNK = 8192
# Un recap puede superar 120 KB con escapes JSON: truncarlo borraría la última
# sesión. El tope sigue acotando basura sin '\n' a lo largo de un fichero.
MAX_FRAGMENT = 1024 * 1024


def _lock(fd: int) -> None:
    """Serializa procesos enteros: `_LOCK` solo cubre hilos. Sin esto, el
    `_repair_tail` de un proceso trunca la línea a medias de otro (medido: 190 de
    200 eventos con 8 procesos en Windows, con líneas vacías)."""
    if sys.platform == "win32":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # reintenta ~10 s
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


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
            _lock(fd)
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
                    raise OSError(f"incomplete write: {written}/{len(data)} bytes")
            finally:
                _unlock(fd)
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
        raise OSError("could not repair the JSONL tail")
    return size + 1
