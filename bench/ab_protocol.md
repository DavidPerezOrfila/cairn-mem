# A/B pequeño y pareado (orientativo)

Objetivo: ¿la memoria de proyecto reduce esfuerzo (tokens, llamadas a herramientas) y
mejora el éxito en tareas que dependen de conocimiento no deducible del código?

Diseño (`bench/ab.py`):

- 8 tareas de respuesta cerrada sobre un proyecto de juguete cuyos datos **no** están en el código.
- Dos brazos, mismo modelo y mismo prompt:
  - **sin**: proyecto limpio, sin `.cairn` ni `AGENTS.md`.
  - **con**: `.cairn` sembrada con los 8 hechos + snippet de `docs/AGENT_SNIPPET.md` en `AGENTS.md`.
- 2 repeticiones por tarea y brazo (32 ejecuciones). Cada ejecución usa una copia limpia del proyecto.
- Métricas: éxito (la respuesta contiene el dato esperado), tokens de entrada/salida, llamadas a herramientas.
- Intervenciones humanas: 0 (se ejecuta con `--auto`).

Con n=8 por brazo el resultado es **orientativo**, no concluyente: mide si la memoria se usa
y si ahorra trabajo, no significación estadística.

Ejecución:

```bash
python bench/ab.py --reps 2          # tabla resumen
python bench/ab.py --reps 2 --json   # filas completas
```
