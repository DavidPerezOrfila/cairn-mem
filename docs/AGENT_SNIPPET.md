# Snippet para AGENTS.md / CLAUDE.md del proyecto que usa cairn-mem

```markdown
## Memoria del proyecto (cairn-mem)
@.cairn/MEMORY.md
<!-- Si tu arnés no soporta @imports: al empezar ejecuta `cairn render` y lee .cairn/MEMORY.md -->

- Si el arnés soporta MCP: arranca `cairn mcp` y usa `search`, `save`, `get`, `context`, `save_session`.
  `context` ya incluye el último resumen de sesión: no hace falta leerlo aparte.
- Si no: al empezar una tarea, `cairn search "<términos>"` (máx. 2–3 búsquedas; cubre proyecto y personal). Detalle: `cairn get <id>`.
- Guarda SOLO cuando: tomas una decisión con motivo, descubres un gotcha, o confirmas una convención.
  `cairn save --kind decision|convention|gotcha|fact --topic <clave/estable> --title "..." --body "<=500 car." --why "..." [--anchor ruta/archivo]`
- Conocimiento válido en cualquier repo (estilo de commits, preferencias del usuario): guárdalo con `--personal`; el `search` normal ya lo encuentra y lo marca `[personal]`.
- Al cerrar una sesión: `cairn session save --summary "<qué se hizo, qué queda>"` (sin límite de 500).
- NO guardes: lo que se deduce leyendo el código o `git log`, estado temporal de la tarea, logs,
  secretos/credenciales/datos de clientes.
- Mismo `--topic` = reemplaza la memoria anterior. No dupliques.
- Si una entrada sale con "⚠ revisar": comprueba el código antes de fiarte; si cambió, reescríbela con el mismo `--topic`.
```
