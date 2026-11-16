# Backlog triggers: medir para cerrar, no para esperar

## Goal

`PLAN.md` §5 tenía cinco mejoras "solo con evidencia medida" y ninguna estaba medida:
el backlog no bloqueaba por falta de código, sino por falta de decisión. Esta ronda mide
lo medible y cierra cada punto con su condición de reapertura.

## Scope

- `bench/bench_retrieval.py --distractors N`: añade memorias de relleno deterministas y
  sin relación con las consultas para medir si el tamaño del índice, por sí solo, degrada
  el ranking.
- `bench/bench_anchors.py`: mide el coste marginal de los anclas en `save` (10k memorias,
  anclas en las filas más recientes, las que caben en el L0).
- `render_l0`: hashea en paralelo los anclas de las filas candidatas (el único arreglo
  seguro del trigger de `anchor_cache`).
- Fuera de alcance: `hits`, decay, `sqlite-vec` y el hook pasivo. No se implementan.

## Decisiones

- `hits`: cerrado. Precision@3 del golden set 30/30 y Hit@3 0.97 en el bench honesto (52 y
  10 052 memorias). El A/B 16/16 es evidencia indirecta (con y sin memoria), no de
  priorización; el ranking medido no muestra fallos.
- `compact`/decay: cerrado. Pasar de 52 a 10 052 memorias sin relación deja Hit@3 en 0.97 y
  Recall@5 en 1.00; el MRR baja 0.96 → 0.94. El L0 ya recorta a 3000 caracteres. Un test
  sintético con duplicados mediría el fixture, no el producto: reabrir exige datos reales.
- `sqlite-vec`: cerrado. Parafraseo Hit@3 0.90 (≥ 0.8) tanto a 52 como a 10 052.
- Hook pasivo: cerrado. En el A/B el agente guardó sin hook; no hay fallo de captura
  medido.
- `anchor_cache`: trigger cumplido (200 anclas de 256 KiB = 50 MB añadían 81 ms al p50 de
  `save`) pero el cache se rechaza. Reutilizar el hash entre comandos por `(size,
  mtime_ns)` es justo lo que `anchor._cached_hash` prohíbe (NTFS actualiza la mtime tarde)
  y cualquier identidad verificada por contenido vuelve a leer el fichero. En su lugar el
  render hashea en paralelo: 81 → 58 ms. Reabrir solo con una identidad de fichero que
  cambie con el contenido sin leerlo (no existe en la stdlib) o si un repo real supera
  p95 500 ms con 10k.

## Acceptance

- `python bench/bench_retrieval.py --distractors 10000` imprime las mismas métricas que a
  52 memorias (Hit@3 y Recall@5; MRR −0.02).
- `python bench/bench_anchors.py --reps 30` mide el marginal de cada escenario y sale 0.
- `pytest -q`: 261 tests, incluida la lectura única por ancla y render, el borde de
  presupuesto con marca stale, anclas ausentes/enormes por el camino paralelo y el relleno
  determinista que no se cuela como respuesta.
- `ruff check src tests bench` limpio.

## Evidence

```text
python bench/bench_retrieval.py --distractors 10000
52 -> 10 052 memories, 37 queries
overall  cairn  Hit@3 0.97  R@5 1.00  MRR 0.94
paraphrase cairn Hit@3 0.90  R@5 1.00  MRR 0.82

python bench/bench_anchors.py --reps 40
sequential (antes del cambio): +81.0 ms marginal con 200 x 256 KiB
paralelo (después):           +58.5 ms marginal con 200 x 256 KiB

python -m pytest -q
261 passed
```
