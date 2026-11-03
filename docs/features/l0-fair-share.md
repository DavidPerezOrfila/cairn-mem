# S1 — L0 reparte el presupuesto entre kinds

**Objetivo:** que un kind con muchas entradas no expulse del L0 a los demás.
El presupuesto sigue siendo 3000 caracteres.

## Alcance

- `Store.active_ordered` devuelve las activas en round-robin por kind: una línea
  de `convention`, una de `decision`, una de `gotcha`, una de `fact`, y se repite.
  Dentro de cada kind, `ts` desc e `id` como desempate.
- Índice parcial `(kind, ts DESC, id) WHERE status = 'active'` para que cada vuelta
  lea 200 filas en vez de escanear la tabla cuatro veces.
- `render.py`, el formato de línea, `EXCERPT`, el límite de 3000 caracteres y el
  cálculo de `stale` no cambian.

Fuera de alcance: cuotas porcentuales configurables, cambio de `kind`, cambio de
`SCHEMA_VERSION` (el índice se crea con `IF NOT EXISTS` al abrir).

## Criterios de aceptación

1. con 4 kinds presentes y 30 decisiones más nuevas, el L0 incluye los cuatro;
2. L0 ≤ 3000 caracteres y byte-idéntico entre dos ejecuciones;
3. `context` MCP p95 < 50 ms con 10k;
4. suite y ruff en verde.

## Evidencia (2026-11-04, repo real y bench de 10k)

| Medida | Antes | Después |
|---|---|---|
| L0 del repo | 2919 car., 15 líneas, **15 `decision`** | 2991 car., 15 líneas, **5 `decision` + 5 `gotcha` + 5 `fact`** |
| `active_ordered` (10k) | 13,3 ms p50 | 8,2 ms p50 |
| `context` MCP (10k) | 18,4 ms p95 (doc) | 23,0 ms p95 (`bench_mcp --reps 20`) |
| `cairn render` e2e | 315–376 ms | 288–393 ms |

- `pytest -q`: 128 passed. `ruff check src tests bench`: limpio.
- `python bench/bench_mcp.py --reps 20`: search 10,6 / save 27,6 / context 23,0 ms p95
  → SLO (< 50 ms) cumple.
