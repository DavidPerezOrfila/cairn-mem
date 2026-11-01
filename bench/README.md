# Medición (M4)
- `bench_cli.py`: tiempo **end-to-end** (incluye arranque de Python) de `cairn search` y `cairn save`, p50/p95, con 1k y 10k registros sintéticos. Ejecutar en la máquina real del usuario (Windows).
- `golden.jsonl`: ~30 pares `{query, expected_id}` sobre memorias sembradas → precisión@3 sin LLM.
- `ab_protocol.md`: A/B pequeño y pareado (ver PLAN.md).
