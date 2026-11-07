# Diseño (v2, tras revisión)

## Objetivo
Memoria persistente para agentes de código: **eficaz, barata en latencia/coste, portable a cualquier arnés con shell**.

## Principios
1. **CLI + archivos.** MCP (v0.2) es una segunda fachada del mismo `Store`; los hooks siguen fuera.
2. **Sin LLM ni embeddings.** FTS5 (BM25) basta hasta que una medición diga lo contrario.
3. **Memoria corta y tipada:** `decision | convention | gotcha | fact`, cuerpo ≤ 500 car., con `why`.
4. **Una sola fuente de verdad:** `events.jsonl`. Todo lo demás (DB, MEMORY.md) es derivado y regenerable.
5. **Lo derivado del entorno no se persiste:** "stale" se calcula al leer.
6. **Simple antes que completo:** cada pieza extra necesita una medición que la justifique (ver backlog).

## Layout
```
.cairn/
  events.jsonl    # VERDAD. Append-only. UTF-8 sin BOM.
  sessions.jsonl  # resúmenes de sesión (append-only, local)
  cairn.db        # derivado (gitignored)
  MEMORY.md       # L0 derivado (gitignored), generado por `cairn render`
  .gitignore      # lo crea `cairn init`
```
- `cairn init` → local-only por defecto (también ignora `events.jsonl`). `cairn init --share` versiona `events.jsonl`.
- Raíz del proyecto: se busca `.cairn/` hacia arriba desde el cwd (como git) o `CAIRN_DIR`. `~/.cairn` y `CAIRN_HOME` se excluyen de esa búsqueda: son el scope personal.
- Scope personal: `CAIRN_HOME` o `~/.cairn`, con el mismo layout; su `MEMORY.md` no se mezcla con el L0 del proyecto.

## Eventos (solo 2 operaciones)
```json
{"op":"save","id":"a1b2c3d4e5f6","ts":1788000000000000000,"kind":"gotcha","topic_key":"auth/redirect","title":"...","body":"...","why":"...","anchor_path":"src/auth.py","anchor_hash":"..."}
{"op":"archive","id":"a1b2c3d4e5f6","ts":1788000000000000001}
```
- `save` con `id` existente = actualización (gana el último).
- `save` con `topic_key` activo = el anterior pasa a `superseded` (se aplica antes de insertar).
- Escritura: **una sola llamada `os.write` con `O_APPEND`**, línea < 4 KB. Sin lock de ficheros (un escritor por proyecto es lo normal; se testea concurrencia ligera).
- Antes de cada append se repara la cola: si el fichero no acaba en `\n` (crash a mitad de write), un fragmento JSON válido conserva la línea y recibe el salto; uno inválido se trunca. Así el siguiente evento nunca queda pegado a una línea rota.
- JSON con `ensure_ascii=False`; ficheros abiertos siempre con `encoding="utf-8"` (Windows).

## Sincronización DB ↔ JSONL
Al abrir el `Store` se compara `(size, mtime_ns)` del JSONL con `meta`. Si difieren (p. ej. tras `git pull`) → `rebuild()` completo (ordenado por `(ts, nº de línea)`) y `render()`. Las escrituras propias actualizan la huella en la misma transacción y comparan la huella **previa al append** (también la `mtime`, no solo el tamaño), para detectar reemplazos externos que conservan el tamaño. `PRAGMA user_version` distinto → se tira el esquema derivado (`mem`, `mem_fts`, `meta`) y se reconstruye.
Coste esperado de rebuild con 10k eventos: del orden de cientos de ms (medido: 570 ms en reposo, S2).

## Escritura y seguridad
- **Rechazar** (no redactar) si el texto parece contener un secreto: claves cloud (`AKIA…`), `-----BEGIN … PRIVATE KEY-----`, JWT (`eyJ…`), tokens con prefijo de proveedor (`ghp_`, `github_pat_`, `glpat-`, `sk-proj-`, `sk-ant-`, `AIza…`), `password|secret|token|api_key = valor`, URLs con `://user:pass@`. Mensaje claro: "reescribe sin el secreto".
- `body` > 500 caracteres → error pidiendo dividir en dos memorias.
- `id` debe ser 12 hex en minúscula; `topic_key` ≤ 100 caracteres y sin caracteres de control (un salto de línea inyectaría líneas en el L0). `render` colapsa además id, título y topic al leer, para eventos externos anteriores a la validación.
- Scrubbing desde M1, **antes** de que nada llegue al JSONL.

## Sesiones (M6)
- Resúmenes de sesión en `.cairn/sessions.jsonl`, append-only y local (gitignored).
- Evento: `{"op":"session","id":"…","ts":…,"summary":"…"}`. Sin límite de 500 caracteres.
- No entran en `events.jsonl`, ni en FTS, ni en L0: son continuidad, no memoria curada.
- Lectura: replay en memoria (son pocos); tolera una última línea rasgada.
- Comandos: `cairn session save|list|get` (con `--personal` para el scope personal). MCP expone solo `save_session` (guardar). La tool `context` devuelve el L0 y, tras él, el último resumen **del proyecto** (máx. 4000 caracteres) para que la sesión nueva arranque sabiendo dónde se quedó la anterior; un resumen personal de otro repo no se mezcla.
- `Sessions.save` pasa por el mismo `reject_secrets` que `Store.save`.

## Scope personal (M7)
- Directorio: `CAIRN_HOME` o `~/.cairn`; `CAIRN_DIR` sigue mandando en el proyecto.
- `save --personal` usa ese `Store`; `get` busca en proyecto y luego en personal.
- `search` es **transversal**: consulta proyecto y personal y entrelaza los resultados
  por posición de ranking (los BM25 de bases distintas no son comparables), empezando
  por el proyecto. Cada resultado lleva `scope`; en texto, el personal va con `[personal]`.
  `--personal` / `scope=personal` restringe a solo personal. Sin `.cairn/` de
  proyecto pero con scope personal, la búsqueda devuelve solo la personal.
- MCP: `scope` en `save` (`project|personal`) y en `search` (`project|personal|all`,
  por defecto `all`).
- El L0 sigue siendo solo del proyecto: la memoria personal no se mezcla en él.

## Importador legacy (M8)
- `cairn import legacy --db RUTA [--dry-run]` lee una base SQLite ajena en solo lectura.
- `type` → `kind`: decision/architecture/config → decision; pattern → convention;
  discovery/bugfix → gotcha; el resto → fact. `session_summary` → `sessions.jsonl`.
- Contenido: `What` → `body` (máx. 500), `Why/Where/Learned` → `why`.
- `project` → `.cairn/` del repo que marca `capture_project_provenance`;
  `global/personal` → scope personal. Borradas y superseded se omiten.
- Id determinista a partir del id de origen y una sal fija: reimportar no duplica.

## Lectura
| Nivel | Qué | Tamaño |
|---|---|---|
| L0 | `.cairn/MEMORY.md`: `- [id] kind: [topic] título — 120 car. de cuerpo` | **≤ 3000 caracteres** (≈ 900 tokens) |
| L1 | `cairn search`: `id, kind, topic_key, title, snippet, stale, scope` | ~50 tokens/resultado |
| L2 | `cairn get <id>`: registro completo | ≤ 500 car. de cuerpo |

- **L0** se regenera tras cada `save/archive` y tras un rebuild. Orden determinista:
  round-robin por `kind` (en cada vuelta, `convention > decision > gotcha > fact`) y
  `ts` desc dentro de cada kind, hasta llenar el presupuesto. Así un kind con muchas
  entradas no expulsa a los demás. El `[topic]` solo aparece si la memoria lo tiene.
- **Búsqueda:** términos saneados (`\w+` → `"t"*`, prefijo), **AND y si no hay resultados OR**;
  `bm25(mem_fts, 5.0, 1.0, 0.5, 3.0, 2.0)` sobre `title, body, why, topic_key, anchor_path`
  (título > topic > ancla > body > why); filtro `status='active'`. Sin más boosts en v0.1.
- Las consultas crudas de FTS5 **fallan** con `-`, `:`, `"` (p. ej. `oauth-callback`); por eso el saneado es obligatorio.

## Anclas / stale (se calcula, no se guarda)
- `anchor_hash` = sha1 del archivo con `\r\n`→`\n` (evita falsos stale entre Windows/Linux).
- `anchor_path` = ruta POSIX relativa a la raíz.
- En `search` y `render`, solo para los resultados devueltos: si el archivo no existe o el hash difiere → `stale=true` → se muestra `⚠ revisar`. No se oculta ni se borra.
- `cairn check` lista todas las stale. Reanclar = `cairn save` con el mismo `--topic` (o `--id`).

## MCP (v0.2)
- Transporte **stdio con NDJSON** (JSON-RPC 2.0), stdlib pura: sin SDK, sin puerto, sin Go.
- `cairn mcp` sirve 5 tools: `save`, `search`, `get`, `context`, `save_session`. El resto
  (mantenimiento) se queda solo en CLI para no pagar sus esquemas en cada turno del modelo.
  `context` inyecta como máximo ~7000 caracteres: L0 (≤ 3000) + último resumen (≤ 4000).
  La tool de sesión se llama `save_session` porque `session` colisiona con el espacio de
  nombres del arnés y OpenCode no la expone.
- El proceso cachea un único `Store`: mientras vive es el único escritor y no paga
  arranque de Python por llamada (search p95 4 ms vs 304 ms de la CLI). Cada lectura
  compara la huella del JSONL y reaplica si cambió por fuera (`git pull`, `cairn` CLI).
- stdout es solo protocolo; diagnóstico por stderr. Lectura bloqueante y salida limpia
  al cerrar el pipe (sin señales, portable a Windows/macOS/Linux).
- Errores de tool van como `isError: true` con texto; errores de protocolo como JSON-RPC.

## Comandos
`init · save · search · get · archive · check · render · rebuild · session · import · mcp`

## Fuera de v0.1 (backlog, solo con evidencia)
hits/ranking por uso · compactación/decay · sqlite-vec · captura pasiva por git hook · LLM `--propose`.
