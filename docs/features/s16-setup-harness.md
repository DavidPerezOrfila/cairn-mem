# S16: `cairn setup <harness>`

## Objetivo

Que un repo quede listo para usar cairn con un solo comando: el servidor MCP declarado
en el fichero que lee el harness y el snippet de reglas en su fichero de instrucciones.

Hoy el usuario copia a mano el bloque JSON del README y el snippet de
`docs/AGENT_SNIPPET.md`. Dos copias manuales, dos oportunidades de dejarse algo.

## Alcance

- `cairn setup claude-code` → `.mcp.json` (`mcpServers.cairn`) + `CLAUDE.md`.
- `cairn setup opencode` → `opencode.json` (`mcp.servers.cairn`) + `AGENTS.md`.
- `--dir PATH` para configurar otra raíz (por defecto el cwd).
- Merge: un fichero de config existente conserva el resto de claves y servidores.
- Idempotente: la segunda ejecución no cambia ni un byte.
- El snippet va entre `<!-- cairn:begin -->` y `<!-- cairn:end -->`, así se refresca sin
  duplicarse ni pisar lo que el usuario haya escrito fuera de las marcas.

Fuera de alcance: codex y cualquier harness cuya ruta/formato de config no se pueda
verificar. Se añade una fila a `HARNESSES` cuando se verifique. Tampoco escribe config
global (`~/.claude.json`, `~/.config/opencode/opencode.json`): el comando trabaja sobre el
repo.

## Criterios de aceptación

- Un `opencode.json` con comentarios (JSONC) no se sobrescribe: el comando falla con
  código 1 y muestra el bloque a pegar a mano.
- Añadir un harness nuevo es una entrada en la tabla `HARNESSES`, sin tocar el resto.
- El snippet del código y el de `docs/AGENT_SNIPPET.md` son el mismo texto (test).
- 0 dependencias nuevas; JSON con la librería estándar.

## Slices

| Slice | Entrega |
| --- | --- |
| S16 | `cairn setup <harness>`, tabla de harnesses, snippet idempotente |
| S16.1 | `cairn export` a Markdown (memoria + sesiones) para un harness sin cairn |

## S16.1: `cairn export`

- `cairn export [--personal] [--sessions N] [--out PATH]`: secciones por kind
  (`convention > decision > gotcha > fact`), la más reciente primero, con id, topic,
  ancla, source, cuerpo y motivo.
- Las sesiones entran solo si se piden (`--sessions N`): son continuidad, no memoria
  curada.
- Sin marcas de stale: hashear las anclas convertiría una foto en un `check`; para eso
  están `search` y `check`.
- Salida determinista (dos ejecuciones, los mismos bytes) para que un diff del `.md`
  signifique algo.

