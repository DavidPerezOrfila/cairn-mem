# S3 — `search` transversal y sesión del proyecto en `context`

**Objetivo:** que una búsqueda encuentre de una vez la memoria del proyecto y la
personal, sin que el agente tenga que adivinar dónde vive lo que busca. Y que
`context` cargue la sesión del proyecto, no un resumen de otro repo.

## Alcance

- `search` (CLI y MCP) consulta proyecto **y** scope personal y entrelaza los
  resultados por posición de ranking (los BM25 de bases distintas no son
  comparables). Cada resultado lleva `scope` (`project|personal`); en texto, el
  scope personal se marca con `[personal]`.
- `--personal` / `scope=personal` sigue siendo el filtro explícito: solo personal.
  MCP acepta además `scope=project`; sin `scope`, `all`.
- Si no hay `~/.cairn`, el proyecto se comporta como antes y no se crea. Si no hay
  proyecto pero sí `~/.cairn`, la búsqueda devuelve la memoria personal; sin ninguno
  de los dos, error con `cairn init`. `--personal` sí crea `~/.cairn` (como `save`).
- `context` devuelve el L0 seguido del último resumen **del proyecto**.

Fuera de alcance: ranking nuevo, cambios en `save`, `get` o `archive`, L0,
importador y sesiones (siguen guardándose por scope).

## Criterios de aceptación

1. Con una memoria del proyecto y otra personal que casan con la consulta, un
   `search` sin filtro devuelve ambas y cada una con su `scope`.
2. `search --personal` y `scope=personal` devuelven solo la personal; `scope=project`
   solo la del proyecto.
3. Sin `~/.cairn`, `search` funciona igual que antes y no crea el directorio. Sin
   `.cairn/` de proyecto pero con personal, devuelve la personal; sin ninguno, error
   con `cairn init`.
4. El límite se aplica al resultado combinado; el reparto es round-robin empezando
   por proyecto (nunca deja fuera a un scope con coincidencias si caben).
5. `context` incluye el último resumen del proyecto e ignora uno personal más
   reciente; `MEMORY.md` no cambia.
6. Suite y `ruff` verdes; precisión@3 30/30; `search` MCP p95 < 50 ms con 10k.

## Evidencia (2026-11-04)

- `pytest -q`: **146 passed** (8 tests nuevos: store, CLI y MCP; 2 existentes se
  reescribieron porque fijaban el comportamiento anterior).
- `ruff check src tests bench`: limpio.
- Precisión@3: 30/30 (`pytest -q tests/test_golden.py`).
- `python bench/bench_cli.py --reps 40` con el scope personal real (18 memorias):
  10k → search p95 309,3 ms, save p95 329,6 ms, interno 4,5 ms. `bench_mcp --reps 40`:
  search 6,6 / save 17,9 / context 12,4 ms p95. Una repetición con el agente
  cargando la CPU dio 13,5 / 29,9 / 31,0 ms p95: en todas, < 50 ms.
- Coste de la segunda base medido aparte (20 repeticiones): `search` MCP p95 7,4 ms
  con `~/.cairn` real frente a 4,7 ms con un `CAIRN_HOME` vacío.
- `cairn search "mcp"` en el repo real (recortado):
  ```text
  24e4a65ea4b2  decision  [cairn/opencode-mcp]  MCP validado en OpenCode — …
  6edbfe4f2ae1  decision  [open-pacman/config/ecc-opencode]  [personal]  MCP de Engram…
  8e7a50e7df08  decision  [cairn/mcp]  MCP por stdio con 4 tools — …
  3b6536818717  gotcha  [06-open-daycare/opencode/engram-mcp-spawn]  [personal]  Fixed…
  c4db88e5939c  decision  [harness/mcp-global]  OpenCode queda solo con el MCP de cairn
  ```
- `context` por el `cairn mcp` real: inyecta el L0 y la sesión del proyecto (el
  resumen de S2), no la sesión personal.
- L0 del repo: 2905 caracteres (sin cambios; esta ronda no toca `MEMORY.md`).
- `~/.cairn` no se crea si no existe: `test_search_does_not_create_personal_dir` (CLI)
  y su equivalente en MCP.

