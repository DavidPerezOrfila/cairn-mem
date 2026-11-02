# A/B pareado (orientativo)

Medición **2026-11-02**, `python bench/ab.py --reps 2` (Windows 11, Python 3.14.10, modelo por defecto de OpenCode).

- 8 tareas de respuesta cerrada sobre un proyecto de juguete; los datos no están en el código.
- 2 brazos × 8 tareas × 2 repeticiones = 32 ejecuciones, cada una en una copia limpia.
- Brazo **con**: `.cairn` sembrada + `AGENTS.md` con `docs/AGENT_SNIPPET.md`.
- Intervenciones humanas: 0 (`--auto`).

| Brazo | Éxito | Tokens (media) | Llamadas a herramientas (media) |
|---|---|---|---|
| sin memoria | 0/16 | 26 826 | 6,3 |
| con memoria | 16/16 | 20 982 | 7,6 |

Lectura: con la memoria el agente acierta siempre y, aunque hace más llamadas (busca y lee
la memoria), gasta menos tokens porque deja de explorar el código sin éxito. El brazo sin
memoria contesta con lo que deduce del código (por ejemplo, "lee `RATE_LIMIT`") y falla.

Con n=8 por brazo esto es **orientativo**: mide que la memoria se usa y ahorra trabajo, no
significación estadística. El protocolo está en [`bench/ab_protocol.md`](../bench/ab_protocol.md).
