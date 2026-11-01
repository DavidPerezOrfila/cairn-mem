# Diseño (v2, tras revisión)

## Objetivo
Memoria persistente para agentes de código: **eficaz, barata en latencia/coste, portable a cualquier arnés con shell**.

## Principios
1. **CLI + archivos.** MCP/hooks son opcionales y quedan fuera de v0.1.
2. **Sin LLM ni embeddings.** FTS5 (BM25) basta hasta que una medición diga lo contrario.
3. **Memoria corta y tipada:** `decision | convention | gotcha | fact`, cuerpo ≤ 500 car., con `why`.
4. **Una sola fuente de verdad:** `events.jsonl`. Todo lo demás (DB, MEMORY.md) es derivado y regenerable.
5. **Lo derivado del entorno no se persiste:** "stale" se calcula al leer.
6. **Simple antes que completo:** cada pieza extra necesita una medición que la justifique (ver backlog).

## Layout
```
.cairn/
  events.jsonl   # VERDAD. Append-only. UTF-8 sin BOM.
  cairn.db       # derivado (gitignored)
  MEMORY.md      # L0 derivado (gitignored), generado por `cairn render`
  .gitignore     # lo crea `cairn init`
```
- `cairn init` → local-only por defecto (también ignora `events.jsonl`). `cairn init --share` versiona `events.jsonl`.
- Raíz del proyecto: se busca `.cairn/` hacia arriba desde el cwd (como git) o `CAIRN_DIR`.

## Eventos (solo 2 operaciones)
```json
{"op":"save","id":"a1b2c3d4e5f6","ts":1788000000000000000,"kind":"gotcha","topic_key":"auth/redirect","title":"...","body":"...","why":"...","anchor_path":"src/auth.py","anchor_hash":"..."}
{"op":"archive","id":"a1b2c3d4e5f6","ts":1788000000000000001}
```
- `save` con `id` existente = actualización (gana el último).
- `save` con `topic_key` activo = el anterior pasa a `superseded` (se aplica antes de insertar).
- Escritura: **una sola llamada `os.write` con `O_APPEND`**, línea < 4 KB. Sin lock de ficheros (un escritor por proyecto es lo normal; se testea concurrencia ligera).
- JSON con `ensure_ascii=False`; ficheros abiertos siempre con `encoding="utf-8"` (Windows).

## Sincronización DB ↔ JSONL
Al abrir el `Store` se compara `(size, mtime_ns)` del JSONL con `meta`. Si difieren (p. ej. tras `git pull`) → `rebuild()` completo (ordenado por `(ts, nº de línea)`) y `render()`. Las escrituras propias actualizan la huella en la misma transacción. `PRAGMA user_version` distinto → rebuild.
Coste esperado de rebuild con 10k eventos: del orden de cientos de ms (medir en M4).

## Escritura y seguridad
- **Rechazar** (no redactar) si el texto parece contener un secreto: claves cloud (`AKIA…`), `-----BEGIN … PRIVATE KEY-----`, JWT (`eyJ…`), `password|secret|token|api_key = valor`, URLs con `://user:pass@`. Mensaje claro: "reescribe sin el secreto".
- `body` > 500 caracteres → error pidiendo dividir en dos memorias.
- Scrubbing desde M1, **antes** de que nada llegue al JSONL.

## Lectura
| Nivel | Qué | Tamaño |
|---|---|---|
| L0 | `.cairn/MEMORY.md`: `- [id] kind: título — 120 car. de cuerpo` | **≤ 3000 caracteres** (≈ 900 tokens) |
| L1 | `cairn search`: `id, kind, title, snippet, stale` | ~50 tokens/resultado |
| L2 | `cairn get <id>`: registro completo | ≤ 500 car. de cuerpo |

- **L0** se regenera tras cada `save/archive` y tras un rebuild. Orden determinista: `convention, decision, gotcha, fact`, luego `ts` desc, hasta llenar el presupuesto.
- **Búsqueda:** términos saneados (`\w+` → `"t"*`, prefijo), **AND y si no hay resultados OR**; `bm25(mem_fts, 5.0, 1.0, 0.5)` (título pesa más); filtro `status='active'`. Sin más boosts en v0.1.
- Las consultas crudas de FTS5 **fallan** con `-`, `:`, `"` (p. ej. `oauth-callback`); por eso el saneado es obligatorio.

## Anclas / stale (se calcula, no se guarda)
- `anchor_hash` = sha1 del archivo con `\r\n`→`\n` (evita falsos stale entre Windows/Linux).
- `anchor_path` = ruta POSIX relativa a la raíz.
- En `search` y `render`, solo para los resultados devueltos: si el archivo no existe o el hash difiere → `stale=true` → se muestra `⚠ revisar`. No se oculta ni se borra.
- `cairn check` lista todas las stale. Reanclar = `cairn save` con el mismo `--topic` (o `--id`).

## Comandos
`init · save · search · get · archive · check · render · rebuild`

## Fuera de v0.1 (backlog, solo con evidencia)
hits/ranking por uso · MCP · compactación/decay · scope global · sqlite-vec · captura pasiva por git hook · LLM `--propose`.
