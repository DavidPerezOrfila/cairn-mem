# AGENTS.md — reglas para construir cairn-mem

## Estado y alcance
- **M6–M9 cerrados y 0.2.1 publicada** (2026-11-03) en PyPI y etiquetada `v0.2.1`. `store.py`, `cli.py`, `anchor.py`, `render.py`, `paths.py`, `mcp.py`, `sessions.py`, `jsonl.py` y `legacy.py` implementados; `tests/` (99) cubre la CLI, el store, L0, anclas, MCP, sesiones, importación y el golden set.
- Implementa **un hito (M#) cada vez** y solo el que toque. Lee `PLAN.md` y `docs/DESIGN.md` antes de codificar.
- Los tests fijan la API exacta (también en el docstring de `store.py`). No los relajes para poner verde.
- Lo siguiente sale del **backlog** y solo con una medición que lo justifique.

## Setup y comandos
```bash
pip install -e ".[dev]"                            # obligatorio; sin esto pytest falla con ModuleNotFoundError
pytest -q
pytest tests/test_store.py::test_save_and_get -q   # un solo test
ruff check src tests bench
python bench/bench_mcp.py --reps 20                 # latencia de tool calls MCP (10k)
```
- Antes de publicar: borra `dist/` **y** `build/`. `uv build` reutiliza `build/lib` y
  empaqueta módulos ya borrados del árbol (un wheel llegó a incluir el importador
  antiguo por un `build/lib/` huérfano).
- CI en `.github/workflows/ci.yml`: ubuntu/macos/windows × Python 3.10 y 3.14 (tests + ruff). Sin config de ruff ni pre-commit: además, verificación local (pytest + ruff + criterios de `PLAN.md`).
- Python 3.10+, **solo stdlib** en el núcleo. `dev` solo aporta pytest y ruff.

## Arquitectura
- `src/cairn_mem/cli.py` (`main(argv) -> int`; entrypoints `cairn` y `cairn-mem`, texto y `--json`), `store.py` (núcleo), `anchor.py` (hash/stale), `render.py` (L0), `paths.py` (raíz `.cairn/` y scope personal), `mcp.py` (stdio JSON-RPC), `sessions.py` (resúmenes), `jsonl.py` (append compartido) y `legacy.py` (importador).
- **Verdad:** `.cairn/events.jsonl` (append-only, 2 ops: `save`, `archive`). `cairn.db` y `MEMORY.md` son derivados y regenerables: no los edites a mano. `sessions.jsonl` es append-only aparte y no es memoria curada.
- `Store(root)` debe crear `.cairn/` y la DB si no existen: los tests lo instancian sin `cairn init`.
- IDs de 12 hex (`secrets.token_hex(6)`) + `ts` en `time_ns`; orden de aplicación `(ts, nº de línea)`. `save` con `topic_key` marca `superseded` el anterior **antes** de insertar.
- Escritura: `O_APPEND` + **una sola** `os.write` por evento; lock en proceso (`jsonl._LOCK`) porque el `O_APPEND` de Windows no es atómico entre hilos.
- Al abrir la DB se compara `(size, mtime_ns)` del JSONL y `PRAGMA user_version`; si difieren → rebuild automático (cubre `git pull`).
- `stale` se calcula al leer; no se persiste ni hay evento de verificación.
- L0 (`.cairn/MEMORY.md`) ≤ 3000 caracteres; round-robin por kind (en cada vuelta `convention > decision > gotcha > fact`) y `ts` desc dentro de cada kind; salida determinista (caché de prompt).
- Raíz del proyecto: busca `.cairn/` hacia arriba desde el cwd o usa `CAIRN_DIR`, excluyendo `~/.cairn` y `CAIRN_HOME` (scope personal). Scope personal: `CAIRN_HOME` o `~/.cairn`.

## Reglas no obvias
- **Windows primero:** todo fichero con `encoding="utf-8"` y JSON con `ensure_ascii=False`; rutas de ancla POSIX relativas a la raíz; hash sha1 con CRLF→LF (si no, falsos stale entre SO). `os.open` del JSONL necesita `O_BINARY` (si no, Windows traduce `\n` a `\r\n`). Commits en LF: `.gitattributes` fija `eol=lf`; no dependas de `core.autocrlf` del clon.
- **FTS5:** nunca pasar texto crudo a `MATCH`; sanea (`\w+` → `"t"*`, prefijo), usa AND y cae a OR si no hay resultados. Crudo falla con `-`, `:`, `"`. Ranking `bm25(mem_fts, 5.0, 1.0, 0.5)`.
- **Seguridad:** rechaza (no redactes) secretos antes de escribir: claves cloud, `BEGIN … PRIVATE KEY`, JWT `eyJ…`, `password|secret|token|api_key` con `=` o `:` (JSON/YAML), URLs `://user:pass@`. `body` > 500 caracteres o `title` > 200 → error.
- Imports mínimos al arranque: SLO de CLI end-to-end (p95 `search` < 350 ms, `save` < 500 ms, arranque incluido) y de tool MCP en proceso (< 50 ms).
- **MCP:** stdout solo protocolo (NDJSON en binario, `\n`); logs a stderr; sin asyncio ni señales; el proceso cachea un `Store` por scope y es el único escritor mientras vive.
- **Sesiones:** `.cairn/sessions.jsonl` es local y no entra en FTS ni L0; un resumen puede superar 500 caracteres.
- **Importador:** idempotente por `sha1("<sal fija>:<id de origen>")[:12]`; `What` → `body` (≤500) y el resto → `why`; `global/personal` va al scope personal y no al repo actual.
- Sin LLM en ninguna ruta. Nada del backlog (`hits`, decay, sqlite-vec, git hook pasivo) sin una medición que lo justifique.
- Cambio de diseño → una fila en `docs/DECISIONS.md` (fecha + decisión + motivo).
- Dogfooding: en cuanto M1 funcione, guarda las decisiones del proyecto con `cairn`.

## Definición de hecho (por hito)
1. Tests del hito en verde, y los de hitos anteriores (un skipped no cuenta).
2. Criterios de aceptación de `PLAN.md` medidos y anotados.
3. Checklist del hito marcada en `PLAN.md`.
