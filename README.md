# cairn-mem

Memoria persistente para agentes de código: **CLI + archivos**, sin LLM y sin dependencias.
Funciona con cualquier agente/arnés que tenga shell.

Una memoria es una decisión, convención, gotcha o hecho del proyecto, con su motivo.
Cairn la guarda en `.cairn/events.jsonl` (append-only, es la verdad) y mantiene un
índice FTS5 y un L0 compacto (`.cairn/MEMORY.md`) que el agente puede leer al arrancar.

## Instalación

```bash
pipx install cairn-mem      # comando global `cairn`
# o, para desarrollar:
pip install -e ".[dev]"
```

## Uso

```bash
cairn init [--share]        # crea .cairn/ (local-only por defecto)
cairn save --kind gotcha --topic auth/redirect --title "..." --body "..." --why "..." --anchor src/auth.py
cairn search "oauth callback" --limit 5     # L1: id, kind, title, snippet, stale
cairn get <id>                              # L2: memoria completa
cairn render                                # L0: regenera e imprime MEMORY.md (≤ 3000 car.)
cairn check                                 # memorias con ancla cambiada (⚠ revisar)
cairn archive <id>                          # deja de aparecer
cairn rebuild                               # reconstruye cairn.db desde events.jsonl
```

- `kind`: `decision | convention | gotcha | fact`. `body` ≤ 500 caracteres.
- Mismo `--topic` reemplaza la memoria anterior; no dupliques.
- `--json` en `save`, `search`, `get` y `check` para consumo desde agentes.
- Secretos: se **rechazan** antes de escribir (claves cloud, JWT, `password = ...`, URLs con credenciales).

## Integración con un agente

Copia el snippet de [`docs/AGENT_SNIPPET.md`](docs/AGENT_SNIPPET.md) en el `AGENTS.md`/`CLAUDE.md`
del proyecto. Verificado guardando en un arnés y recuperando en otro (OpenCode y GitHub Copilot CLI).

## Diseño

- Verdad: `.cairn/events.jsonl` (2 operaciones: `save`, `archive`).
- Derivados y regenerables: `cairn.db` (SQLite + FTS5) y `MEMORY.md`.
- Búsqueda BM25 con consultas saneadas (AND y fallback OR), sin embeddings.
- `stale` se calcula al leer comparando el hash del ancla (CRLF→LF), no se persiste.
- Detalle: [`docs/DESIGN.md`](docs/DESIGN.md) · Decisiones: [`docs/DECISIONS.md`](docs/DECISIONS.md) · Medidas: [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

## Estado

v0.1.0. Hitos: [`PLAN.md`](PLAN.md). Reglas de desarrollo: [`AGENTS.md`](AGENTS.md).

## Desarrollo

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests bench
python bench/bench_cli.py --reps 20
```

Python 3.10+; el núcleo usa solo la stdlib.
