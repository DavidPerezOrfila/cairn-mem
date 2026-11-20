# S21: A/B de escritura, `setup` sin duplicar y `CAIRN_LANG`

## Goal

Tres huecos de la auditoría del 2026-11-18:

1. El A/B (16/16) medía **recuperación**, nunca si el agente **escribe** lo que
   descubre. Sin esa medida, el riesgo "el agente no guarda memorias" no tenía
   número.
2. `setup claude-code` + `setup opencode` dejaban el bloque de reglas en
   `CLAUDE.md` y en `AGENTS.md`; si Claude importa `@AGENTS.md`, lo leía dos veces.
3. CLI, `doctor` y `setup` hablaban en español mientras el L0 y el MCP ya estaban
   en inglés, y el borde del store (errores que llegan a una tool MCP) seguía en
   español.

## Scope

- **`bench/ab_write.py`**: una sesión por corrida sobre un repo de juguete donde el
  agente cambia el campo `time` de `/health` a epoch porque el equipo de datos lo consume
  desde otra zona horaria. El **motivo** solo existe en la petición, no en el código, así
  que es la "decisión con razón" que el snippet manda guardar. El éxito es un `save`
  **nuevo** en `events.jsonl` cuyo texto menciona el tema (`epoch|utc|tz|timezone|iso|
  timestamp`). Brazos: `plain` (control), `empty` (instalación normal), `stale` (ancla
  desfasada), `poison` (memoria que la petición contradice) y `distractors` (100
  rellenos). Criterios en
  [`bench/ab_write_protocol.md`](../../bench/ab_write_protocol.md), escritos antes
  de medir: n ≥ 30 por brazo, Wilson 95%, `empty` con cota inferior ≥ 0,5 y sin
  solape con `plain`, controles a menos de 0,20 de `empty`.
- **`setup.py`**: si el fichero de instrucciones no es `AGENTS.md` e importa
  `@AGENTS.md` (`@AGENTS.md` o `@./AGENTS.md` en una línea), no se escribe el
  bloque y se borra el que dejó una instalación anterior. El mensaje dice qué
  hizo (`importa @AGENTS.md; ya estaba|bloque duplicado eliminado`).
- **`i18n.py`**: `t(en, es)` con `CAIRN_LANG` leído en cada llamada (testeable sin
  recargar módulos); cualquier valor que no empiece por `es` cae en inglés.
  `cli.py`, `doctor.py` y `setup.py` pasan por ahí. `store`, `sessions`,
  `anchor`, `paths`, `jsonl`, `mcp` y `export` quedan **solo en inglés**: un error
  de tool MCP no puede cambiar de idioma con el entorno. De paso se unificó la
  superficie del agente: `⚠ review`, `## Last session`, `unknown tool`, `# cairn
  memory`, `Why:` en el export, y el snippet cita la marca que la CLI imprime.

## Notas

- El snippet sigue siendo conservador ("Do NOT save: anything you can work out
  from the code"), así que el escenario tiene que aportar conocimiento que el
  código no contenga. Se descartaron dos versiones antes de medir (un bug de una
  línea: 0/5; un gotcha de entorno que el agente arreglaba en `conftest.py`: 0/2) y
  ambas quedan escritas en el protocolo para que nadie las "arregle" volviendo
  atrás.
- Los criterios no dependen del escenario: el único cambio permitido fue el
  escenario, y está documentado con fecha.
- **Resultado (2026-11-20):** `bench/ab_write.py --arms empty,plain --reps 30` →
  `empty` 2/30 (IC95 0,018-0,213) y `plain` 0/30 (0,000-0,114), 0 exits
  non-zero. El criterio 1 (cota inferior ≥ 0,5 y sin solape con `plain`) falla:
  el snippet no basta para que este modelo guarde la decisión. Los brazos de
  control no se corrieron porque su margen de 0,20 no es medible a 2/30. Números
  en [`docs/AB_RESULTS.md`](../../docs/AB_RESULTS.md); el riesgo "el agente no
  guarda memorias" sigue abierto en `PLAN.md` §6.

## Tests

`tests/test_i18n.py` (variantes de `CAIRN_LANG`, CLI/doctor/setup en los dos
idiomas, `--json` intacto), `tests/test_ab_write.py` (detección de `save` nuevo
con el gotcha, Wilson, limpieza del temporal y `--json` con un `_run` falso) y
`tests/test_setup.py` (import sin bloque, bloque viejo eliminado). Los tests
existentes pasan a esperar los mensajes en inglés; el español se cubre en
`test_i18n.py`.
