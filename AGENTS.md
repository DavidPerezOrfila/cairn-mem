# AGENTS.md — reglas para construir cairn-mem

## Contexto
Lee `PLAN.md` y `docs/DESIGN.md` antes de tocar código. Trabaja **un hito (M#) cada vez**.
Si algo se puede hacer de forma simple, hazlo simple. Nada del **backlog** sin una medición que lo justifique.

## Reglas
- **Python 3.10+, solo stdlib.** Cero dependencias en el núcleo.
- **TDD:** test rojo → implementación mínima → verde → refactor. Muestra la salida real de `pytest`.
- **Sin LLM** en ninguna ruta.
- **Fuente de verdad:** `.cairn/events.jsonl` (append-only, 2 ops: `save`, `archive`). `cairn.db` y `MEMORY.md` son derivados.
- **Windows primero:** ficheros siempre `encoding="utf-8"`, JSON con `ensure_ascii=False`, rutas ancla en POSIX relativo, hash con CRLF→LF.
- **Seguridad:** rechazar secretos antes de escribir (ver DESIGN).
- **Consultas FTS5:** nunca pasar texto crudo del usuario a `MATCH`; usar el saneado.
- Cambios de diseño → una línea en `docs/DECISIONS.md` (fecha + motivo).
- Dogfooding: usa `cairn` en este mismo repo para guardar decisiones del proyecto en cuanto M1 funcione.

## Definición de hecho (por hito)
1. Tests del hito en verde (y los de hitos anteriores).
2. Criterios de aceptación de `PLAN.md` medidos y anotados.
3. Checklist del hito marcada.

## Comandos
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```
