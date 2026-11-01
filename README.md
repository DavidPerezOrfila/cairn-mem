# cairn-mem

Memoria persistente para agentes de código: **CLI + archivos**, sin LLM y sin dependencias.
Funciona con cualquier agente/arnés que tenga shell.

- Plan: [`PLAN.md`](PLAN.md) · Diseño: [`docs/DESIGN.md`](docs/DESIGN.md) · Reglas para el agente constructor: [`AGENTS.md`](AGENTS.md)
- Cómo usarla desde un agente: [`docs/AGENT_SNIPPET.md`](docs/AGENT_SNIPPET.md)

## Estado
M0 listo (esqueleto + tests rojos de M1). Siguiente: **M1**.

## Uso previsto
```bash
cairn init [--share]
cairn save --kind gotcha --topic auth/redirect --title "..." --body "..." --why "..." --anchor src/auth.py
cairn search "oauth callback" --limit 5     # L1
cairn get <id>                              # L2
cairn check                                 # lista memorias con ancla cambiada (⚠ revisar)
cairn archive <id>
cairn render                                # regenera .cairn/MEMORY.md (L0)
cairn rebuild                               # reconstruye cairn.db desde events.jsonl
```
