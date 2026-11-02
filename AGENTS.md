# AGENTS.md — reglas para construir cairn-mem

## Estado y alcance
- **M4 cerrado.** v0.1.0 publicada en PyPI. `store.py`, `cli.py`, `anchor.py` y `render.py` implementados; `tests/` cubre la CLI, el store, L0, anclas y el golden set.
- Implementa **un hito (M#) cada vez** y solo el que toque. Lee `PLAN.md` y `docs/DESIGN.md` antes de codificar.
- Los tests fijan la API exacta (también en el docstring de `store.py`). No los relajes para poner verde.
- Lo siguiente sale del **backlog** y solo con una medición que lo justifique.

## Setup y comandos
```bash
pip install -e ".[dev]"                            # obligatorio; sin esto pytest falla con ModuleNotFoundError
pytest -q
pytest tests/test_store.py::test_save_and_get -q   # un solo test
ruff check src tests
python scripts/export.py <carpeta_vacia>           # export multiplataforma, solo stdlib
```
- No hay CI, ni config de ruff, ni pre-commit: la verificación es local (pytest + ruff + criterios de `PLAN.md`).
- Python 3.10+, **solo stdlib** en el núcleo. `dev` solo aporta pytest y ruff.

## Arquitectura
- `src/cairn_mem/cli.py` (`main(argv) -> int`; entrypoints `cairn` y `cairn-mem`, texto y `--json`), `store.py` (núcleo), `anchor.py` (hash/stale) y `render.py` (L0).
- **Verdad:** `.cairn/events.jsonl` (append-only, 2 ops: `save`, `archive`). `cairn.db` y `MEMORY.md` son derivados y regenerables: no los edites a mano.
- `Store(root)` debe crear `.cairn/` y la DB si no existen: los tests lo instancian sin `cairn init`.
- IDs de 12 hex (`secrets.token_hex(6)`) + `ts` en `time_ns`; orden de aplicación `(ts, nº de línea)`. `save` con `topic_key` marca `superseded` el anterior **antes** de insertar.
- Escritura: `O_APPEND` + **una sola** `os.write` por evento, sin locks.
- Al abrir la DB se compara `(size, mtime_ns)` del JSONL y `PRAGMA user_version`; si difieren → rebuild automático (cubre `git pull`).
- `stale` se calcula al leer; no se persiste ni hay evento de verificación.
- L0 (`.cairn/MEMORY.md`) ≤ 3000 caracteres; orden `convention > decision > gotcha > fact` y `ts` desc; salida determinista (caché de prompt).
- Raíz del proyecto: busca `.cairn/` hacia arriba desde el cwd o usa `CAIRN_DIR`.

## Reglas no obvias
- **Windows primero:** todo fichero con `encoding="utf-8"` y JSON con `ensure_ascii=False`; rutas de ancla POSIX relativas a la raíz; hash sha1 con CRLF→LF (si no, falsos stale entre SO). `os.open` del JSONL necesita `O_BINARY` (si no, Windows traduce `\n` a `\r\n`). Commits en LF: el repo no tiene `.gitattributes` y `core.autocrlf=true`.
- **FTS5:** nunca pasar texto crudo a `MATCH`; sanea (`\w+` → `"t"*`, prefijo), usa AND y cae a OR si no hay resultados. Crudo falla con `-`, `:`, `"`. Ranking `bm25(mem_fts, 5.0, 1.0, 0.5)`.
- **Seguridad:** rechaza (no redactes) secretos antes de escribir: claves cloud, `BEGIN … PRIVATE KEY`, JWT `eyJ…`, `password|secret|token|api_key = valor`, URLs `://user:pass@`. `body` > 500 caracteres → error.
- Imports mínimos al arranque: el SLO es end-to-end (p95 `search` < 150 ms, `save` < 200 ms, arranque de Python incluido).
- Sin LLM en ninguna ruta. Nada del backlog (`hits`, MCP, decay, sqlite-vec, git hook pasivo) sin una medición que lo justifique.
- Cambio de diseño → una fila en `docs/DECISIONS.md` (fecha + decisión + motivo).
- Dogfooding: en cuanto M1 funcione, guarda las decisiones del proyecto con `cairn`.

## Definición de hecho (por hito)
1. Tests del hito en verde, y los de hitos anteriores (un skipped no cuenta).
2. Criterios de aceptación de `PLAN.md` medidos y anotados.
3. Checklist del hito marcada en `PLAN.md`.
