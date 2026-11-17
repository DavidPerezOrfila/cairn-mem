# S15: anotaciones MCP, `--read-only` y filtros de `search`

## Goal

Que un cliente MCP que respeta las anotaciones auto-apruebe lo seguro y pida
confirmación para lo demás, y que quien use varios agentes pueda registrar dos
servidores (uno de escritura, otro de lectura para subagentes review/explore)
sin depender de reglas de permisos en el prompt.

## Scope

- `mcp.py`: las 8 tools llevan `annotations`
  (`readOnlyHint`, `destructiveHint`, `idempotentHint`):
  - `search`, `get`, `context`, `session_list`, `session_get`:
    `readOnlyHint: true, destructiveHint: false, idempotentHint: true`.
  - `save`, `save_session`: `readOnlyHint: false, destructiveHint: false`.
  - `archive`: `readOnlyHint: false, destructiveHint: true, idempotentHint: true`
    (archivar dos veces deja el mismo estado).
- `cairn mcp --read-only`: `tools/list` expone solo las 5 tools de lectura y
  `tools/call` rechaza las de escritura con el error JSON-RPC -32602 en el
  borde del protocolo, antes de tocar el `Store`.
- `cli.py`: flag `--read-only` en el subcomando `mcp`.

## Acceptance criteria

1. `tools/list` devuelve anotaciones coherentes en las 8 tools
   (`tests/test_mcp.py::test_tools_carry_annotations`).
2. `Server(read_only=True)` lista solo las 5 de lectura y rechaza `save`
   sin escribir nada en `events.jsonl`
   (`test_read_only_server_exposes_and_allows_only_read_tools`).
3. Subprocess con `cairn mcp --read-only`: `tools/list` con 5 tools y
   `archive` rechazado con -32602 (`test_mcp_read_only_flag_subprocess`).

## Evidence

Gate medido 2026-11-16: `pytest -q` → 264 passed; `ruff check src tests bench`
limpio. Los benches no cambian: `bench_mcp` no pasa por `--read-only`.

## Resto de S15 (2026-11-17)

- `search --kind/--topic/--stale` en CLI y MCP; los filtros van al WHERE de SQL.
  `--topic` es el `topic_key` exacto.
- Con `--stale` no se aplica el LIMIT de SQL (los primeros K por bm25 pueden estar
  frescos): se recorre el ranking y se corta al reunir `limit` filas stale.
- `partial` es un campo de salida, no un flag de entrada: se marca en las filas que
  vienen del fallback OR.
- `Sessions._records` falla con `sessions.jsonl línea N: sesión inválida` salvo cola
  rasgada (sin `\n` final).

Aceptación: `test_search_filters_by_kind_and_topic`,
`test_search_marks_rows_from_the_or_fallback_as_partial`,
`test_search_stale_skips_fresh_rows_before_applying_the_limit`,
`test_search_kind_topic_and_stale_flags`, `test_search_filters_by_kind_and_marks_partial_rows`,
`test_invalid_session_mid_file_fails_naming_the_line`.

## Out of scope

- Modo read-only en la CLI general (los comandos de escritura siguen ahí:
  la proteccción es por servidor MCP, no por shell).
