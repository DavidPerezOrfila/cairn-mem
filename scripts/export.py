"""Exporta este proyecto a una carpeta VACÍA (multiplataforma, solo stdlib).
Uso: python scripts/export.py <carpeta_destino>
"""
import shutil
import sys
from pathlib import Path

IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", ".pytest_cache", "*.egg-info",
                                "cairn.db", "cairn.db-*", "MEMORY.md")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    dest = Path(sys.argv[1]).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        print(f"ERROR: {dest} no está vacía", file=sys.stderr)
        return 1
    src = Path(__file__).resolve().parent.parent
    shutil.copytree(src, dest, ignore=IGNORE, dirs_exist_ok=True)
    print(f"Exportado a {dest}")
    print("Siguiente: git init && python -m venv .venv && pip install -e \".[dev]\" && pytest -q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
