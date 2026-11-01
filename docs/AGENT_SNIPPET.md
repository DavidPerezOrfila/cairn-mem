# Snippet para AGENTS.md / CLAUDE.md del proyecto que usa cairn-mem

```markdown
## Memoria del proyecto (cairn-mem)
@.cairn/MEMORY.md
<!-- Si tu arnés no soporta @imports: al empezar ejecuta `cairn render` y lee .cairn/MEMORY.md -->

- Al empezar una tarea: `cairn search "<términos>"` (máx. 2–3 búsquedas). Detalle: `cairn get <id>`.
- Guarda SOLO cuando: tomas una decisión con motivo, descubres un gotcha, o confirmas una convención.
  `cairn save --kind decision|convention|gotcha|fact --topic <clave/estable> --title "..." --body "<=500 car." --why "..." [--anchor ruta/archivo]`
- NO guardes: lo que se deduce leyendo el código o `git log`, estado temporal de la tarea, logs,
  secretos/credenciales/datos de clientes.
- Mismo `--topic` = reemplaza la memoria anterior. No dupliques.
- Si una entrada sale con "⚠ revisar": comprueba el código antes de fiarte; si cambió, reescríbela con el mismo `--topic`.
```
