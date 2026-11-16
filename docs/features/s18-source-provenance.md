# S18: procedencia opcional (`source`) en cada memoria

## Goal

Saber quién escribió cada memoria (agente, modelo o sesión) para poder revisar
la memoria en el PR con contexto y mitigar el envenenamiento por alucinación.
La memoria la escribe un agente autónomo: la procedencia es lo que el revisor
humano pregunta primero.

## Decision (docs/DECISIONS.md)

Sin estado "sin revisar" y sin comando de aprobación: un flujo de aprobación
añadiría un tercer tipo de evento y una reescritura por memoria en Git. Con
`--share`, el PR sobre `events.jsonl` **ya es** la revisión humana. `source`
solo responde "quién lo escribió", que es lo que esa revisión necesita.

## Scope

- `events.jsonl`: `source` opcional en el evento `save`
  (los eventos previos no lo llevan y siguen aplicando).
- `mem.source` en SQLite (`SCHEMA_VERSION = 4`: las DB derivadas se tiran y
  se reconstruyen al abrir, sin migración manual).
- `Store.save(source=...)`: normalizado como el `topic_key` (sin saltos de
  línea ni controles, ≤ 100 caracteres, strip) y pasado por `reject_secrets`.
  `parse_event` lo valida también al leer (tipo, longitud y controles).
- `parse_event`: `source` debe ser string o estar ausente; un valor no string
  falla con `events.jsonl línea N`.
- CLI: `cairn save --source`; el texto de `search` añade `(source)` cuando
  existe; `get` lo muestra. En JSON de `search`, `source` solo aparece cuando
  hay valor (ruido de tokens fuera).
- MCP: `source` (≤ 100) en el esquema de `save`.
- El L0 no lo muestra: el presupuesto es de 3000 caracteres y la procedencia
  vive en el evento, no en la línea del prompt.

## Acceptance criteria

1. `save` con `source` → `get`, `search` (JSON y texto) y un `rebuild` la
   conservan (`tests/test_store.py::test_save_with_source_roundtrip`,
   `test_source_survives_rebuild`).
2. Sin `source`, el campo no aparece en `search` y queda `None` en `get`.
3. Validación en escritura y en `parse_event` (`test_source_is_validated_at_write`,
   `test_parse_event_rejects_non_string_source`).
4. CLI y MCP exponen `source` (`test_cli.py::test_save_with_source_shows_provenance`,
   `test_mcp.py::test_save_accepts_source`).

## Evidence

Gate medido 2026-11-16: `pytest -q` → 272 passed (8 tests nuevos, rojos antes
de la implementación); `ruff check src tests bench` limpio. Los SLOs no
cambian: el coste es una columna más en `INSERT` y el rebuild por versión se
paga una vez al abrir.

## Out of scope

- Estado "sin revisar", comando de aprobación o filtro por `source` en
  `search` (se añadiría con la S15 pendiente: `search --kind/--topic`).
- `source` en sesiones (`sessions.jsonl`): no es memoria curada.
