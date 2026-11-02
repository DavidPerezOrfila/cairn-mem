"""Anclas de fichero: hash estable entre SO y stale calculado al leer."""

import hashlib
from pathlib import Path


def file_hash(path) -> str:
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha1(data).hexdigest()


def is_stale(anchor_path, anchor_hash, project_root) -> bool:
    if not anchor_path or not anchor_hash:
        return False
    try:
        return file_hash(Path(project_root) / anchor_path) != anchor_hash
    except OSError:
        # No se pudo leer (falta, es carpeta o está bloqueado): no se puede
        # confirmar el hash, así que se avisa. Nunca se oculta la memoria.
        return True
