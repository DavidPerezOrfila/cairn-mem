# S22: retrieval fields and concurrency

## Goal

Tres huecos de S22: una consulta cuyos términos no están en la memoria no la
encuentra ("dónde guardo las contraseñas" → "Cifrado de secretos en reposo"),
el historial de un `topic_key` ya existe en el JSONL pero no se puede leer, y el
append concurrente solo está probado entre hilos, no entre procesos.

## Scope

1. **`keywords` indexado en FTS** (`SCHEMA_VERSION = 6`). Campo opcional de
   `save` (CLI `--keywords`, tool MCP `save`): sinónimos con los que el autor
   quiere que la memoria aparezca. Se indexa como 6ª columna entre `topic_key` y
   `anchor_path`, con el mismo peso que el topic (3.0). Validación y
   `parse_event` como el resto del metadato: sin controles, ≤ 200 caracteres,
   espacios normalizados, vacío → `None`, y pasa por `reject_secrets`. El L0 no
   cambia. `cairn get` lo muestra porque lee la fila completa.
2. **`cairn history <topic> [--json]`**: todas las versiones de un `topic_key`
   (activa, superseded y archivadas) de la más vieja a la más nueva, con su
   estado. Los superseded ya viven en la DB derivada; no hay grafo ni comando
   nuevo por scope (recorre proyecto y personal como `topics`).
3. **Test multiproceso**: 8 procesos (`subprocess`, instalación real del
   paquete) × 25 appends en el mismo `events.jsonl`; el fichero queda con 200
   líneas JSON válidas y el `Store` lo reconstruye. Cubre el riesgo de
   `jsonl._LOCK` (solo intra-proceso) y `_repair_tail`.

## Acceptance criteria

1. Gate de S22: `bench/paraphrase.jsonl` no retrocede y mejora P@3 (léxico 8/8,
   flexión 8/8, paráfrasis 9/10 → 10/10). `tests/test_s22.py` lo fija en CI.
2. `keywords` sobrevive al rebuild, se busca por sus sinónimos, y un evento
   externo con `keywords` inválidos falla con `ValueError`.
3. `cairn history` devuelve las versiones en orden con su estado y `--json`
   incluye `scope`; un topic desconocido no es un error.
4. `pytest -q` verde, `ruff check src tests bench` limpio y los SLO de
   `bench_cli`/`bench_mcp`/`bench_sync` intactos.

## Slices

1. `keywords` + esquema 6 + CLI/MCP + gate de paráfrasis.
2. `history` (store + CLI).
3. Test multiproceso del append.

## Evidence

Gate medido 2026-11-20 (detalle en `docs/BENCHMARKS.md`, § S22):

- Paráfrasis: 9/10 → 10/10; overall Hit@3 0.96 → 1.00, MRR 0.94 → 0.98; léxico
  y flexión sin cambio. Sin `keywords` en el fixture las métricas son idénticas
  al baseline (la columna vacía no altera el ranking).
- `bench/retrieval.jsonl`: 0.97 / 1.00 / 0.96, igual que antes.
- Append multiproceso: antes del lock, 8 procesos × 25 appends dejaban 190, 195 y 197
  líneas válidas de 200 (ids perdidos y líneas vacías); con el lock, 5/5 intentos con
  200/200 líneas y el test sembrando una cola rasgada.
- `bench_mcp`: save p95 16.9 ms, search 4.0 ms, context 5.3 ms. `bench_sync`: save p95
  17.4 ms, search 4.8 ms. `bench_cli` (10k): search e2e p95 206 ms, save p95 222 ms,
  consulta interna 1.9 ms; los tres SLO se cumplen.
- `pytest -q`: 427 passed, 4 xfailed; `ruff check src tests bench` limpio.
