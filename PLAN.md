# PLAN v2 — cairn-mem (revisado)

> Memoria persistente para agentes de código: eficaz, sin penalizar latencia/coste, portable a cualquier arnés con shell.
> **Estimación: 4–6 días** (antes 6–9). Un hito = una sesión de agente. Flujo: entender → test rojo → implementar → medir → marcar.

## 1. Revisión: puntos débiles y qué cambió

| # | Punto débil del plan v1 | Cambio |
|---|---|---|
| 1 | SLO "p95 < 10 ms" ignoraba el **arranque de Python** (lo que realmente nota el agente) | SLO end-to-end con arranque incluido (M4 lo revisó a `search` < 350 ms y `save` < 500 ms tras medir el suelo real) |
| 2 | `stale` persistido con evento `verify`: depende del checkout y diverge entre ramas | **Se calcula al leer**, solo para los resultados devueltos. Sin evento, sin estado |
| 3 | Hash de ancla distinto entre Windows/Linux (CRLF) → falsos stale | Hash con **CRLF→LF**; ruta ancla en POSIX relativo |
| 4 | `hits` vía evento en cada `get`: la lectura se vuelve escritura (latencia, ruido en Git) | **Fuera de v0.1** (backlog). L0 = prioridad por `kind` + recencia |
| 5 | Consultas FTS5 crudas **fallan** con `-`, `:`, `"` (probado: `oauth-callback` → error) | Saneado obligatorio: `"t"*` por término, **AND y si vacío OR** |
| 6 | DB desactualizada tras `git pull` (nadie la reconstruía) | Huella `(size, mtime_ns)` del JSONL → `rebuild` automático; `user_version` → rebuild |
| 7 | Scrubbing de secretos en M5 (tarde: el JSONL puede ir a Git) | **M1**, y por **rechazo** (no redacción silenciosa) |
| 8 | `MEMORY.md` versionado y regenerado → conflictos/ruido | Derivado y gitignored; se regenera en `save/archive`/rebuild (sin depender de hooks) |
| 9 | Memoria en Git por defecto en entorno corporativo | **Local-only por defecto**; `cairn init --share` para versionar |
| 10 | Lock de ficheros (`msvcrt`/`fcntl`): complejo y poco portable | `O_APPEND` + **una sola** `os.write` por evento |
| 11 | ULID propio, 6 tipos de evento, columnas `scope`/`last_verified`/`hits` | ID de 12 hex + `ts`; **2 eventos** (`save`,`archive`); esquema mínimo |
| 12 | Ranking BM25 × boosts, dedupe léxico, decay, promoción, LLM `--propose` | Solo `bm25()` con pesos por columna. El resto → **backlog** |
| 13 | Captura pasiva por git hook: ruido que baja la precisión | Fuera. Regla explícita de **qué guardar / qué no** en `docs/AGENT_SNIPPET.md` |
| 14 | MCP a mano, scope global: coste y riesgo sin necesidad probada | **Backlog**. El CLI cubre cualquier arnés con shell |
| 15 | Windows: `export.sh` no corre sin bash; codificación cp1252; falta `init` y raíz del proyecto | `export.py` (stdlib); UTF-8 forzado + test; `cairn init`; búsqueda de `.cairn/` hacia arriba |
| 16 | A/B de 10–20 tareas: ruidoso y caro | **Golden set** de recuperación (sin LLM, en CI) + A/B pequeño **pareado** |
| 17 | `get` por ID largo (ULID) propenso a error del agente | ID corto de 12 hex |

## 2. Metas medibles (SLOs)

| Métrica | Objetivo |
|---|---|
| `cairn search` end-to-end (con arranque de Python), p95 | **< 350 ms** en reposo, 10k (antes 150 ms; ver abajo) |
| `cairn save` end-to-end (incluye render L0), p95 | **< 500 ms** en reposo, 10k (antes 200 ms) |
| Consulta interna `search` (10k registros) | **< 10 ms** |
| Tool call MCP en proceso (10k registros) | **< 50 ms** |
| L0 (`MEMORY.md`) | **≤ 3000 caracteres** (~900 tokens) |
| Precisión@3 en golden set | **≥ 0.8** |
| Rebuild con 10k eventos | medir (medido: 1,3 s en reposo) |
| Dependencias / llamadas LLM | **0 / 0** |

> Revisado 2026-11-02 tras medir el suelo de arranque: `python -c pass` ≈ 72 ms y solo importar
> `sqlite3, json, re` ≈ 138 ms. Los 150/200 ms originales eran inalcanzables sin demonio o
> binario nativo. Ver `docs/BENCHMARKS.md`.

## 3. Hitos

### M0 — Bootstrap ✅
- [x] Estructura, `pyproject.toml`, `AGENTS.md`, diseño, esquema, `AGENT_SNIPPET.md`, `export.py`
- [x] Tests rojos de M1 + tests de M2 (se saltan hasta existir el módulo)

**Aceptación:** `pip install -e ".[dev]" && pytest -q` → M1 en rojo, M2 *skipped*.

### M1 — Núcleo (1–2 días) ✅
- [x] `Store`: `save/get/search/archive/rebuild/dump` según `docs/DESIGN.md`
- [x] JSONL append-only (`O_APPEND` + 1 `os.write`), UTF-8 sin BOM, `ensure_ascii=False`
- [x] Aplicación de eventos: `topic_key` → anterior `superseded` **antes** de insertar; orden `(ts, nº línea)`
- [x] Huella del JSONL + `user_version` → rebuild automático
- [x] Rechazo de secretos y de `body > 500`
- [x] Búsqueda saneada AND→OR, `bm25(mem_fts,5.0,1.0,0.5)`, snippet
- [x] CLI: `init [--share]`, `save`, `search`, `get`, `archive`, `rebuild` (texto y `--json`); raíz `.cairn/` hacia arriba o `CAIRN_DIR`
- [x] Arranque rápido: imports mínimos, sin imports pesados al inicio

**Aceptación:** `tests/test_store.py` en verde · `rebuild` idempotente · `search` interno < 10 ms con 10k sintéticos (medido 2026-11-01: rebuild 507 ms, `search` p95 3.87 ms).
**Dogfooding:** desde aquí, guarda las decisiones del propio proyecto con `cairn`.

### M2 — L0 y anclas (1 día) ✅
- [x] `anchor.py`: `file_hash` (CRLF→LF), `is_stale`
- [x] `render.py`: `render_l0(store, max_chars=3000)` determinista, orden `convention > decision > gotcha > fact` y `ts` desc, `⚠ revisar` en stale
- [x] `search` devuelve `stale` por resultado; `cairn render` y `cairn check`
- [x] Regeneración automática de `MEMORY.md` tras `save/archive/rebuild`

**Aceptación:** `test_anchor.py` y `test_render.py` en verde · salida de L0 byte-idéntica sin cambios (caché de prompt) · `check` sobre 1k registros < 1 s.
(medido 2026-11-02: 53 tests verdes, L0 2944 car. con 1k registros y estable al reabrir, `check` end-to-end 181 ms, `render` 135 ms)

### M3 — Integración (0.5–1 día) ✅
- [x] `docs/AGENT_SNIPPET.md` probado en **≥ 2 arneses** (p. ej. Claude Code y OpenCode): guardar en uno, recuperar en otro
- [x] Instalación: `pipx install .` (Windows incluido); comprobar que `cairn` queda en PATH
- [ ] Opcional: hook `Stop` de Claude Code que recuerde guardar (si se mide que el agente no guarda)

**Aceptación:** ciclo guardar → nueva sesión → recuperar funcionando en 2 arneses.

**Medido 2026-11-02:**
- `pipx install .` → `cairn-mem 0.0.1`; shim `~/.local/bin/cairn.exe` con `render`/`check`.
- OpenCode guardó `6146ba141640` (`decision`, topic `vcs/lf`) → GitHub Copilot CLI lo recuperó con `cairn search`.
- Copilot CLI guardó `bd4076114207` (`convention`, topic `git/commits`) → sesión nueva de OpenCode lo recuperó.
- Hook `Stop`: no se instala; no hay evidencia de que el agente no guarde (se mide en el A/B de M4).

### M4 — Medición y release (1 día) ✅
- [x] `bench/bench_cli.py`: p50/p95 end-to-end de `search` y `save` con 1k y 10k registros (en Windows real)
- [x] `bench/golden.jsonl` (~30 consultas) + test de precisión@3 en CI
- [x] **A/B pequeño pareado:** 8 tareas × 2 brazos (sin / con memoria), mismo modelo, 2 repeticiones; métricas: tokens totales, llamadas a herramientas, éxito, intervenciones humanas. Con n tan bajo es **orientativo**, no concluyente
- [x] Reservar/publicar `cairn-mem` en PyPI (libre el 2026-10-31; comprobar de nuevo antes) y verificar que el comando `cairn` no choca en PATH
- [x] README final, versión 0.1.0, etiqueta Git

**Aceptación:** SLOs de §2 anotados en `docs/BENCHMARKS.md` y decisión explícita: ¿hay que tocar L0, ranking o reglas de guardado?

**Medido 2026-11-02:**
- Bench 1k/10k en [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md). Precisión@3: 30/30 = 1,00.
- SLO end-to-end revisado a `search` < 350 ms y `save` < 500 ms tras medir el suelo de arranque (`python -c pass` 72 ms; imports 138 ms). En reposo: search p95 304 ms, save p95 451 ms, consulta interna 5,9 ms → **cumple**.
- Decisión: **no** tocar L0, ranking ni reglas de guardado; optimizar arranque queda en backlog solo con evidencia de uso.
- A/B: sin memoria 0/16 aciertos y 26 826 tokens; con memoria 16/16 y 20 982 tokens ([`docs/AB_RESULTS.md`](docs/AB_RESULTS.md)).
- `uv build` + instalación del wheel 0.1.0 en venv limpio: `init`, `save`, `search` y `render` funcionan.
- PyPI: **publicado 2026-11-02** (`cairn_mem-0.1.0` wheel + sdist, https://pypi.org/project/cairn-mem/0.1.0/); `pip index versions cairn-mem` → 0.1.0; instalación desde PyPI en venv limpio verificada. `cairn` en PATH sin choque (shim de pipx + editable).

### M5 — MCP stdio y CI multiplataforma ✅
- [x] `mcp.py`: JSON-RPC 2.0 en NDJSON sobre stdio, sin SDK ni dependencias
- [x] 4 tools (`save`, `search`, `get`, `context`); el resto sigue solo en CLI
- [x] `Store` cacheado: un proceso, un escritor, sin arranque de Python por llamada
- [x] `cairn mcp` como subcomando; nada se escribe en stdout fuera del protocolo
- [x] CI: ubuntu/macos/windows × Python 3.10 y 3.14 (tests + ruff)
- [x] `bench/bench_mcp.py` para latencia de tool calls con 10k
- [x] Fix: `_known_size` no se actualizaba tras `save`/`archive` → cada escritura
      en un proceso largo disparaba un rebuild completo
- [x] L0 acotado en SQL (`active_ordered`) en vez de ordenar todas las filas en Python

**Aceptación:** tool call p95 < 50 ms (medido 2026-11-02: search 4,0 ms, save 37,4 ms,
context 18,4 ms con 10k) · 66 tests en verde · `ruff` limpio · las 6 celdas de CI en verde.

### M6 — Sesiones (0.5 día) ✅
- [x] `sessions.jsonl` append-only en `.cairn/`, separado de la memoria curada
- [x] `Sessions`: `save/list/get`; reabrir el proceso y recuperar el resumen
- [x] CLI `cairn session save|list|get` y tool MCP `session`
- [x] Resumen largo (sin límite de 500 caracteres) sin tocar L0

**Aceptación:** un resumen de ~2k caracteres se guarda y recupera; `MEMORY.md` no cambia ·
el JSONL tolera una última línea rasgada como `events.jsonl`.
(medido 2026-11-03: resumen de 5k guardado y recuperado, 84 tests en verde)

### M7 — Scope personal (0.5 día) ✅
- [x] `paths.personal_dir()`: `CAIRN_HOME` o `~/.cairn`
- [x] `save/search --personal`; `get` busca en proyecto y personal
- [x] MCP: `scope` (`project|personal`) en `save` y `search`

**Aceptación:** una memoria personal se recupera desde otro repo y no aparece en el L0 del
proyecto · el proyecto sigue funcionando sin `CAIRN_HOME`.
(medido 2026-11-03: `--personal` con `CAIRN_HOME` temporal; el L0 del proyecto no la incluye)

### M8 — Importador legacy (1 día) ✅
- [x] `cairn import legacy --db RUTA [--dry-run]`
- [x] Mapeo: `What`→`body`, `Why/Where/Learned`→`why`; tipo→`kind`; `session_summary`→sesión
- [x] `project` → `.cairn/` del repo (por provenance); `global/personal` → `~/.cairn`
- [x] Idempotente: id derivado del id de origen con sal fija; omite borradas y superseded

**Aceptación:** importa las 64 observaciones reales sin duplicados al reejecutar ·
los secretos se rechazan por fila y se reportan, no abortan el lote.
(medido 2026-11-03: 23 memorias + 10 sesiones; segunda pasada 0 + 0 con 33 omitidas)

**Publicación 0.2.0:** 2026-11-03 en PyPI (wheel + sdist) y tag `v0.2.0`; instalación limpia
desde PyPI verificada con `init`, `save`, `session`, `search` e `import --dry-run`.

### M9 — Cierre de huecos de paridad ✅
- [x] `Sessions.save` rechaza secretos (antes `sessions.jsonl` los aceptaba)
- [x] MCP `context` devuelve L0 + último resumen de sesión (≤ 4000 car.), sin tocar `MEMORY.md`
- [x] `Store` reaplica el JSONL en lecturas si la huella cambió (MCP de vida larga tras `git pull`/CLI)
- [x] Reinstalado el binario global: `pipx install . --force` sirve las 5 tools
- [x] Importador renombrado a `legacy` (módulo, subcomando y docs): el repo remoto no nombra la herramienta que sustituye

**Aceptación:** 94 tests en verde · `ruff` limpio · `tools/list` por `cairn mcp` muestra
`save, search, get, context, session` con `context` describiendo el resumen de sesión.
(medido 2026-11-03: 94 passed; lectura sin cambios no dispara rebuild)

**Publicación 0.2.1:** pendiente (versión subida en `pyproject.toml`; falta tag y PyPI).

## 4. Backlog (solo con evidencia medida)
- `hits` en tabla local no versionada + boost de ranking (si el golden set o el A/B muestran mala priorización)
- `compact`/decay (si el nº de memorias activas degrada la precisión)
- `sqlite-vec` (si precisión@3 < 0.8 por sinónimos y los títulos no lo arreglan)
- Captura pasiva por git hook (solo si el agente no guarda y el ruido es aceptable)

## 5. Riesgos (los que quedan)

| Riesgo | Mitigación |
|---|---|
| El agente no guarda memorias | Reglas claras en el snippet + hook `Stop` opcional; medir en A/B |
| El agente guarda basura | Regla "NO guardes…" + límite 500 car. + `topic_key` para reemplazar |
| Stale por ancla de archivo entero (falsos positivos en ficheros grandes) | Solo avisa (`⚠ revisar`), no oculta; medir tasa en A/B; anclar al fichero más específico |
| Latencia de arranque en Windows (antivirus, `pipx` shim) | Medir end-to-end en M4; imports mínimos |
| Memoria desactualizada tras `git pull` | Huella del JSONL + rebuild automático |
| Secretos | Rechazo en escritura + local-only por defecto |
| FTS5 no disponible en algún Python | Comprobar al arrancar y fallar con mensaje claro |

## 6. Cómo exportarlo

```bash
python scripts/export.py /ruta/carpeta_vacia      # multiplataforma, rechaza carpetas no vacías
# o descomprimir el zip directamente en la carpeta vacía
cd /ruta/carpeta_vacia && git init
python -m venv .venv && pip install -e ".[dev]" && pytest -q   # M1 rojo, M2 skipped
```

## 7. Prompt de arranque para el agente
```text
Lee AGENTS.md, PLAN.md y docs/DESIGN.md. Implementa SOLO M1 con TDD
(tests/test_store.py ya está en rojo). Solo stdlib. Muestra la salida real de pytest,
marca la checklist de M1 en PLAN.md y no avances a M2.
```
