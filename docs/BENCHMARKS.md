# Benchmarks (M4)

Medición **2026-11-02** en la máquina real del usuario.

- Windows 11 Pro 10.0.26300, 16 GB RAM, Python 3.14.10.
- Carga del sistema durante la medición: ~54 % (procesos del editor/agente en marcha).
- Comando: `python bench/bench_cli.py --reps 20` (sembrado por JSONL + rebuild; la CLI se mide con `python -m cairn_mem.cli`, arranque de Python incluido).

## Latencia end-to-end

| Registros | rebuild | search p50 | search p95 | save p50 | save p95 | search interno p95 |
|---|---|---|---|---|---|---|
| 1 000 | 212 ms | 353 ms | 378 ms | 387 ms | 398 ms | 1,1 ms |
| 10 000 | 1 816 ms | 361 ms | 390 ms | 534 ms | 636 ms | 4,8 ms |

## Precisión@3

`python -m pytest tests/test_golden.py` → **30/30 = 1,00** (golden set de 20 memorias y 30 consultas, sin LLM).

## Veredicto frente a §2 del PLAN

- `search` interno: **cumple** (< 10 ms).
- Precisión@3: **cumple** (≥ 0,8).
- Rebuild 10k: 1,8 s (el PLAN pedía medirlo, no fijaba objetivo).
- `search`/`save` end-to-end: **no cumplen** (< 150/200 ms) en esta medición.

## Por qué falla el end-to-end

Medido con `python -X importtime` y procesos mínimos:

- `python -c pass`: ~100 ms en esta máquina.
- Importar `cairn_mem.store`: ~130–200 ms (`json`, `re`, `secrets`, `sqlite3`, `pathlib`).
- `argparse` de Python 3.14 añade ~150 ms (`_colorize`, `dataclasses`, `inspect`, `shutil`).

La consulta en sí es 1–5 ms; el coste es arranque del intérprete + imports de stdlib. Una medición previa del mismo día, con la máquina menos cargada, dio `search` 130 ms y `check` 181 ms, así que el objetivo no está descartado por diseño, pero no se sostiene con esta carga.

## Decisión

No se toca L0, ni el ranking, ni las reglas de guardado: la búsqueda interna y la precisión cumplen, y el margen está en el arranque del proceso, no en el diseño de la memoria. Antes de publicar en PyPI, repetir `bench_cli.py` con la máquina en reposo y anotar el resultado aquí.

L0 con 1k memorias: 2 944 caracteres (≤ 3 000) y byte-idéntico al reabrir (ver `PLAN.md`, M2).
