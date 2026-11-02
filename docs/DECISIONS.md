# Decisiones (ADR corto)

| Fecha | Decisión | Motivo |
|---|---|---|
| 2026-10-31 | IDs de 12 hex aleatorios + `ts` aparte (no ULID, no enteros) | Cortos de teclear para el agente, sin colisiones en merge, orden por `ts` |
| 2026-10-31 | 2 operaciones de evento (`save`, `archive`) | Menos superficie; supersede se deriva de `topic_key` |
| 2026-10-31 | `stale` calculado al leer, no persistido | Depende del checkout; persistirlo causa verdades contradictorias entre ramas |
| 2026-10-31 | Sin `hits` en v0.1 | Convertía `get` en escritura (latencia, ruido en Git). Reintroducir solo si el A/B lo justifica |
| 2026-10-31 | Sin lock de ficheros: `O_APPEND` + 1 `os.write` | Portable y suficiente; evita `msvcrt`/`fcntl` |
| 2026-10-31 | `MEMORY.md` y `cairn.db` derivados y gitignored | Evita conflictos de merge y ruido en diffs |
| 2026-10-31 | Local-only por defecto (`--share` para versionar) | Entorno corporativo: la memoria puede contener contexto interno |
| 2026-10-31 | Scrubbing en M1 y por **rechazo** | Un secreto en JSONL versionado es el peor fallo; redactar en silencio corrompe la memoria |
| 2026-10-31 | Búsqueda saneada AND→OR | FTS5 crudo falla con `-`, `:`, `"` |
| 2026-10-31 | MCP, compact/decay, git hook pasivo, scope global → backlog | No hay medición que los justifique; el CLI ya cubre cualquier arnés con shell |
| 2026-10-31 | SLO de latencia medido end-to-end (con arranque de Python) | La consulta en sí es ms; lo que nota el agente es el proceso |
| 2026-10-31 | FTS5 sin vectores | Latencia/coste; `sqlite-vec` solo si el recall medido es malo |
| 2026-10-31 | Nombre: **cairn-mem** (paquete PyPI), módulo `cairn_mem`, comando `cairn`, datos en `.cairn/` | Metáfora de marcas para quien viene detrás; `cairn` suelto ya existe en PyPI, `cairn-mem` estaba libre (comprobado 2026-10-31) |
| 2026-11-01 | `ts` > int64 se recorta a `2**63-1` al aplicar a SQLite; el JSONL conserva el original | SQLite usa enteros signed de 64 bits: un evento importado con `ts` mayor rompía el rebuild con `OverflowError` |
| 2026-11-01 | `rebuild` tolera JSON inválido solo en la última línea no vacía | Un crash a mitad de `os.write` dejaría el Store inutilizable en cada apertura; una línea intermedia corrupta sigue fallando en voz alta |
| 2026-11-01 | La huella del JSONL se captura al terminar el append, no tras aplicar el evento | Evita certificar como aplicados eventos externos que llegaron entre ambas operaciones |
| 2026-11-01 | El append usa `O_BINARY` (Windows) | `os.open` en modo texto traduce `\n` a `\r\n`; el JSONL quedaba con CRLF y el guard de tamaño lo detectaba como evento externo |
| 2026-11-02 | Lock en proceso alrededor del append del JSONL | El `O_APPEND` del CRT de Windows no es atómico entre hilos: el test de concurrencia perdía líneas (19/20). Entre procesos se mantiene la regla de un escritor por proyecto |
| 2026-11-02 | SLO end-to-end revisado a `search` < 350 ms y `save` < 500 ms | Medido el suelo: `python -c pass` 72 ms e importar `sqlite3, json, re` 138 ms; los 150/200 ms originales exigían demonio o binario nativo. No se toca L0, ranking ni guardado |
| 2026-11-02 | Publicada la v0.1.0 en PyPI como `cairn-mem` (wheel + sdist) | Nombre libre y verificado; el comando `cairn` no choca con el shim de pipx ni con el editable |
| 2026-11-02 | MCP por stdio con JSON-RPC a mano (stdlib), no SDK | Mantiene `dependencies = []`, funciona en los 3 SO sin Go y elimina el arranque de Python por llamada |
| 2026-11-02 | MCP expone solo `save/search/get/context` | 4 esquemas cuestan ~500 tokens fijos por turno; el mantenimiento no necesita estar en el prompt |
| 2026-11-02 | CI con matriz ubuntu/macos/windows × 3.10/3.14 | "Windows primero" se verificaba a mano; el framing stdio y las rutas necesitan prueba real por SO |
| 2026-11-02 | `_known_size` se actualiza tras `save`/`archive` | Un `Store` de vida larga (MCP) reconstruía la DB en cada escritura: save p95 pasó de 3,4 s a 37 ms |
| 2026-11-02 | Ancla confinada al proyecto con `Path.relative_to` | `os.path.relpath` no falla con `../` dentro de la misma unidad: el ancla podía salir del repo y filtrar rutas |
