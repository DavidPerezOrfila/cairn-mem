"""Mensajes humanos: inglés por defecto y `CAIRN_LANG=es` opt-in (S21).

La superficie del agente (L0 y MCP) no pasa por aquí: `store`, `sessions`, `anchor`,
`paths` y `jsonl` hablan siempre inglés, porque un error del agente no puede cambiar de
idioma con el entorno de quien lanzó el harness.
"""

import os


def language() -> str:
    value = os.environ.get("CAIRN_LANG", "").strip().lower()
    return "es" if value.startswith("es") else "en"


def t(en: str, es: str) -> str:
    """Devuelve el mensaje del idioma activo (`CAIRN_LANG`, inglés por defecto)."""
    return es if language() == "es" else en
