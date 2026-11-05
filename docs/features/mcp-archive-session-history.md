# S4 — `archive` por MCP y consulta de sesiones anteriores

**Objetivo:** paridad CLI↔MCP completa. El agente puede retirar una memoria sin salir
del arnés y puede mirar sesiones anteriores sin sobreescribir el contexto actual
(`context` solo entrega la última; hoy no hay forma de consultar la anterior).

## Alcance

- Tres tools nuevas en `mcp.py`, sin cambios en `store.py`, `sessions.py` ni CLI:
  - `archive` (`id` requerido, `scope` `project|personal`): archiva la memoria como
    `cairn archive`; error si no existe (el store no valida).
  - `session_list` (`limit` opcional 1–50, por defecto 20; `scope`): lista reciente
    en JSON con `{id, ts, preview}` (resumen colapsado, 200 primeros caracteres).
  - `session_get` (`id` requerido, `scope`): devuelve el registro completo en JSON;
    error si no existe.
- Nombres evitando `session` / `sessions` solos: OpenCode ya filtró una tool por
  colisión de nombre (0.2.2).
- Re-archivar una memoria ya archivada reescribe el evento de archive (el store solo
  exige que exista), igual que la CLI: no es error, pero sí un evento por llamada.
- Sin tool `rebuild`, `render` ni `check`: son mantenimiento, no flujo del agente.

Fuera de alcance: CLI (ya tiene todo), L0, ranking, importador.

## Criterios de aceptación

1. `tools/list` muestra `save, search, get, context, save_session, archive,
   session_list, session_get`.
2. `archive` por MCP archiva en proyecto y en scope personal; id inexistente → error
   estructurado (`isError`).
3. `session_list` devuelve las sesiones por recencia respetando `limit`; `session_get`
   trae el resumen completo; id inexistente → error.
4. `scope` controla la raíz: `personal` no mezcla sesiones del proyecto.
5. `limit` se recorta al rango 1–50 (y `limit` no numérico → error estructurado).
6. Suite y `ruff` verdes; una repetición de `bench_mcp` sin regresión en las tools
   medidas.

## Evidencia (2026-11-05)

- `pytest -q`: **153 passed** (7 tests nuevos, `tests/test_mcp.py`; el test de
  `tools/list` se reescribió para el set completo). 7 en rojo antes de implementar.
- `ruff check src tests bench`: limpio.
- `bench/bench_mcp.py --reps 20` con 10k: search p95 5,9 ms / save 23,0 ms /
  context 14,3 ms (**SLO p95 < 50 ms: OK**).
- `bench/bench_cli.py --reps 20` (10k): primera pasada con ruido (search p95
  384–414 ms, save 241–366 ms). Pasada pareada consecutiva baseline v0.5.0 → rama:
  v0.5.0 search p95 340,6 / save 364,0; rama search p95 321,9 / save 339,2 ms.
  **SLO search < 350, save < 500: OK en ambas**; el ruido era de la máquina, no del
  código (el CLI de `search` no se toca; interno 2,8 vs 3,1 ms).
- Ciclo MCP real: `save` → `archive` → `search` ya no la devuelve y `dump` la marca
  `archived`; `save_session` × 2 → `session_list` más nueva primero con preview y
  `session_get` devuelve el resumen completo; `scope=personal` no mezcla sesiones.
- Errata del desarrollo: la primera versión de `_session_root` evaluaba
  `if _scope(...)`, truthy para `"project"`, y siempre leía el scope personal;
  el test de scope lo detectó.
