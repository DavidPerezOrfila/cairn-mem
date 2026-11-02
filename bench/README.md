# Medición (M4)
- `bench_cli.py`: tiempo **end-to-end** (incluye arranque de Python) de `cairn search` y `cairn save`, p50/p95, con 1k y 10k registros sintéticos. Ejecutar en la máquina real del usuario (Windows): `python bench/bench_cli.py --reps 20 [--json]`. Resultados en [`docs/BENCHMARKS.md`](../docs/BENCHMARKS.md).
- `golden.jsonl`: 20 memorias sembradas y ~30 consultas `{query, expected title}` → precisión@3 sin LLM (`tests/test_golden.py`).
- `ab_protocol.md`: A/B pequeño y pareado (ver PLAN.md); `ab.py` lo ejecuta con OpenCode. Resultados en [`docs/AB_RESULTS.md`](../docs/AB_RESULTS.md).
