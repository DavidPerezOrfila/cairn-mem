# S2 — `topic_key` visible y buscable

**Objetivo:** que la clave estable de una memoria (`topic_key`) se vea en el L0 y en
`search`, y que FTS5 la indexe junto con la ruta del ancla. Así el agente puede pedir
"lo de `storage/fts5`" o "lo de `src/auth.py`" sin recordar el título.

## Alcance

- FTS5 pasa a indexar `topic_key` y `anchor_path` además de `title`, `body` y `why`.
  Pesos BM25: título 5, topic 3, ancla 2, body 1, why 0.5.
- `search` devuelve `topic_key` en JSON y lo muestra en texto cuando existe.
- El L0 muestra `[topic]` entre el `kind` y el título, solo si la memoria tiene topic.
- `SCHEMA_VERSION` 2 → 3. Al abrir una DB vieja se borra el esquema derivado y se
  reconstruye desde `events.jsonl`; no hay migración manual ni evento nuevo.

Fuera de alcance: cuotas de L0, ranking nuevo, `hits`, cambios en `archive` o MCP tools.

## Criterios de aceptación

1. `search "storage/fts5"` y `search "src/auth"` encuentran la memoria por topic y ancla.
2. `search --json` incluye `topic_key`; el texto lo muestra sin romper el formato actual.
3. El L0 incluye `[topic]` cuando existe, sigue ≤ 3000 caracteres y es determinista.
4. Una DB con `user_version = 2` se reconstruye sola al abrirla y queda buscable por topic.
5. Precisión@3 sigue en 30/30; suite y `ruff` verdes; `search` MCP p95 < 50 ms con 10k.

## Evidencia (2026-11-04)

- `pytest -q`: **137 passed** (9 tests nuevos: store, render, CLI y MCP).
- `ruff check src tests bench`: limpio.
- Precisión@3: 30/30 (`pytest -q tests/test_golden.py`).
- Migración real: el store del repo pasó de `user_version=2` a 3 al abrirse, sin tocar
  el JSONL; `cairn search "release/0.3.1"` devuelve la memoria por topic.
- `python bench/bench_cli.py --reps 20` (10k): search p95 150,6 ms, save p95 137,8 ms,
  interno 2,2 ms. `bench_mcp`: search 2,3 / save 9,4 / context 5,8 ms p95.
- L0 del repo: 2927 caracteres, 14 líneas, `[topic]` visible en todas.
- Baseline de topics: 39 activas, 39 con `topic_key`, 4 claves repetidas incluyendo
  superseded (5 superseded). No hay duplicados activos (índice único parcial).
