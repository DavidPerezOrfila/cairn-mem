# Benchmarks (M4)

Medición **2026-11-02** en la máquina real del usuario.

- Windows 11 Pro 10.0.26300, 16 GB RAM, Python 3.14.10.
- Comando: `python bench/bench_cli.py --reps 20` (sembrado por JSONL + rebuild; la CLI se mide con `python -m cairn_mem.cli`, arranque de Python incluido).

## Latencia end-to-end

| Registros | Carga | rebuild | search p50 | search p95 | save p50 | save p95 | search interno p95 |
|---|---|---|---|---|---|---|---|
| 1 000 | 54 % | 212 ms | 353 ms | 378 ms | 387 ms | 398 ms | 1,1 ms |
| 10 000 | 54 % | 1 816 ms | 361 ms | 390 ms | 534 ms | 636 ms | 4,8 ms |
| 1 000 | 16 % | 172 ms | 292 ms | 317 ms | 318 ms | 331 ms | 0,8 ms |
| 10 000 | 16 % | 1 303 ms | 283 ms | 304 ms | 439 ms | 451 ms | 5,9 ms |

La primera pasada se hizo con el editor/agente ocupando la CPU; la segunda con la máquina en reposo (16 %).

## MCP (tool call en proceso, 10k registros)

`python bench/bench_mcp.py --reps 20` (2026-11-02, misma máquina):

| Tool | p50 | p95 |
|---|---|---|
| `search` | 3,4 ms | 4,0 ms |
| `save` | 28,4 ms | 37,4 ms |
| `context` (L0) | 14,5 ms | 18,4 ms |

SLO nuevo: tool call p95 < 50 ms → **cumple** sin arranque de Python.

## Precisión@3

`python -m pytest tests/test_golden.py` → **30/30 = 1,00** (golden set de 20 memorias y 30 consultas, sin LLM).

## Suelo de arranque

Medido en reposo (10 ejecuciones, p50):

| Proceso | p50 |
|---|---|
| `python -c pass` | 72 ms |
| `import sqlite3, json, re` | 138 ms |
| `import sqlite3, json, re, secrets, hashlib, pathlib` | 169 ms |
| `import cairn_mem.cli` | 178 ms |

El SLO original (`search` < 150 ms) está por debajo del coste de importar la stdlib necesaria antes de tocar la base: no es alcanzable sin cambiar la arquitectura (demonio o binario nativo). Por eso §2 del PLAN se revisa con esta medición: `search` p95 < 350 ms y `save` p95 < 500 ms en reposo con 10k.

## Veredicto frente a §2 del PLAN (revisado)

- `search` interno: **cumple** (< 10 ms).
- Precisión@3: **cumple** (≥ 0,8).
- `search` e2e en reposo: **cumple** (304 ms < 350 ms). `save`: **cumple** (451 ms < 500 ms).
- Rebuild 10k: 1,3 s (el PLAN pedía medirlo, no fijaba objetivo).

## Decisión

No se toca L0, ni el ranking, ni las reglas de guardado: la consulta interna y la precisión cumplen, y el margen está en el arranque del proceso, no en el diseño de la memoria. Optimizar el arranque (parser propio, imports perezosos) queda en backlog solo si el A/B o el uso real muestran que molesta.

L0 con 1k memorias: 2 944 caracteres (≤ 3 000) y byte-idéntico al reabrir (ver `PLAN.md`, M2).

## L0 round-robin (S1, 2026-11-04)

`python bench/bench_mcp.py --reps 20` con 10k registros, misma máquina:

| Tool | p50 | p95 |
|---|---|---|
| `search` | 6,7 ms | 10,6 ms |
| `save` | 24,2 ms | 27,6 ms |
| `context` (L0) | 18,0 ms | 23,0 ms |

- `active_ordered` con 10k: 8,2 ms p50 (antes 13,3 ms p50).
- `cairn render` end-to-end: 288–393 ms (antes 315–376 ms el mismo día).
- L0 del repo: 2919 caracteres y 15 líneas `decision` → 2991 caracteres con
  5 `decision`, 5 `gotcha` y 5 `fact`.
- Detalle y criterios: [`docs/features/l0-fair-share.md`](features/l0-fair-share.md).
