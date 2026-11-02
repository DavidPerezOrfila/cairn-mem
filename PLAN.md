# PLAN v2 — cairn-mem (revisado)

> Memoria persistente para agentes de código: eficaz, sin penalizar latencia/coste, portable a cualquier arnés con shell.
> **Estimación: 4–6 días** (antes 6–9). Un hito = una sesión de agente. Flujo: entender → test rojo → implementar → medir → marcar.

## 1. Revisión: puntos débiles y qué cambió

| # | Punto débil del plan v1 | Cambio |
|---|---|---|
| 1 | SLO "p95 < 10 ms" ignoraba el **arranque de Python** (lo que realmente nota el agente) | SLO end-to-end: `search` p95 **< 150 ms** en la máquina real; la consulta interna sigue < 10 ms |
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
| `cairn search` end-to-end (con arranque de Python), p95 | **< 150 ms** (medir en Windows real) |
| `cairn save` end-to-end (incluye render L0), p95 | **< 200 ms** |
| Consulta interna `search` (10k registros) | **< 10 ms** |
| L0 (`MEMORY.md`) | **≤ 3000 caracteres** (~900 tokens) |
| Precisión@3 en golden set | **≥ 0.8** |
| Rebuild con 10k eventos | medir (esperado: cientos de ms) |
| Dependencias / llamadas LLM | **0 / 0** |

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

### M4 — Medición y release (1 día)
- [ ] `bench/bench_cli.py`: p50/p95 end-to-end de `search` y `save` con 1k y 10k registros (en Windows real)
- [ ] `bench/golden.jsonl` (~30 consultas) + test de precisión@3 en CI
- [ ] **A/B pequeño pareado:** 8 tareas × 2 brazos (sin / con memoria), mismo modelo, 2 repeticiones; métricas: tokens totales, llamadas a herramientas, éxito, intervenciones humanas. Con n tan bajo es **orientativo**, no concluyente
- [ ] Reservar/publicar `cairn-mem` en PyPI (libre el 2026-10-31; comprobar de nuevo antes) y verificar que el comando `cairn` no choca en PATH
- [ ] README final, versión 0.1.0, etiqueta Git

**Aceptación:** SLOs de §2 anotados en `docs/BENCHMARKS.md` y decisión explícita: ¿hay que tocar L0, ranking o reglas de guardado?

## 4. Backlog (solo con evidencia medida)
- `hits` en tabla local no versionada + boost de ranking (si el golden set o el A/B muestran mala priorización)
- Adaptador MCP (si aparece un arnés sin shell)
- `compact`/decay (si el nº de memorias activas degrada la precisión)
- `sqlite-vec` (si precisión@3 < 0.8 por sinónimos y los títulos no lo arreglan)
- Scope global `~/.cairn-mem`
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
