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
| 2026-11-03 | Sesiones en `sessions.jsonl`, no en `events.jsonl` | Un resumen de sesión es continuidad (2–5k car.), no memoria curada; si entrara, rompería el límite de 500 y el L0 |
| 2026-11-03 | Scope personal en `CAIRN_HOME` o `~/.cairn` | Hay conocimiento transversal que vale en cualquier repo; el L0 del proyecto no lo mezcla y `search --personal` lo consulta aparte |
| 2026-11-03 | Import legacy con id derivado del id de origen y sal fija | Reimportar no duplica y el orden se conserva con el `ts` original |
| 2026-11-03 | Import: `What` → `body`, resto → `why`; `global/personal` → scope personal | Respeta el límite de 500 sin partir memorias; el detalle queda buscable y la ubicación no mezcla repos |
| 2026-11-03 | `append_jsonl` compartido por Store y Sessions | El lock de Windows y el `O_BINARY` deben ser los mismos en ambos JSONL; duplicarlo invitaba a divergir |
| 2026-11-03 | `data_dir` excluye `~/.cairn` y `CAIRN_HOME` de la búsqueda hacia arriba | Con el scope personal en `~/.cairn`, cualquier cwd bajo el home lo encontraba como raíz de proyecto y `cairn search` leía la memoria personal sin avisar |
| 2026-11-03 | Las sesiones pasan por `reject_secrets` | `events.jsonl` ya rechazaba secretos, pero `sessions.jsonl` los aceptaba: un resumen con un token acababa en disco sin aviso |
| 2026-11-03 | La tool MCP `context` añade el último resumen de sesión (recortado a 4000 car.) | `session` era write-only por MCP: el agente guardaba al cerrar y no recuperaba nada al empezar. `MEMORY.md` sigue siendo solo memoria curada |
| 2026-11-03 | `Store` reaplica el JSONL en las lecturas si la huella cambió | El `Store` del MCP vive horas: tras un `git pull` o un `save` desde la CLI, `search`/`get`/`context` servían datos viejos |
| 2026-11-03 | El importador se llama `legacy` (módulo, subcomando y docs) | La herramienta que sustituye no debe aparecer en el repo remoto; el id conserva la sal antigua para no duplicar lo ya importado |
| 2026-11-03 | La tool MCP de sesión se llama `save_session` | `session` colisiona con el espacio de nombres del arnés: OpenCode no la exponía y el agente no podía guardar el resumen |
| 2026-11-03 | Rebuild captura la huella antes de leer y archive usa un `ts` posterior al save (`SCHEMA_VERSION=2`) | Un append externo a mitad del rebuild quedaba certificado sin aplicar; un save importado con `ts` futuro resucitaba al reconstruir. El bump fuerza un rebuild de las DB ya envenenadas |
| 2026-11-03 | `title` se normaliza y se limita a 200 caracteres | Un título largo vaciaba el L0 (el render corta en la primera línea que no cabe) y un salto de línea rompía el formato |
| 2026-11-03 | `init` rechaza el scope personal y los stores anidados; re-init en su raíz sigue permitido | En el home creaba un store invisible para `data_dir`; en un subdirectorio partía la memoria en dos |
| 2026-11-03 | El filtro de secretos acepta `:` y comillas, y claves compuestas (`DB_PASSWORD`, `api-key`) | YAML y JSON eran los formatos más probables de fuga y pasaban el filtro |
| 2026-11-03 | Anchors > 2 MB se marcan stale sin hashear en `search`; `cairn check` hashea siempre | Leer varios ficheros grandes por búsqueda podía recorrer cientos de MB |
| 2026-11-04 | L0 reparte el presupuesto en round-robin por `kind` (una línea de cada uno por vuelta) | Con 15 `decision` en el repo, los `gotcha` y `fact` existentes nunca entraban en los 3000 caracteres |
| 2026-11-04 | Índice parcial `(kind, ts DESC, id) WHERE status='active'` | Sin él, el reparto hacía cuatro escaneos de la tabla: `context` pasaba de 18 a 89 ms p95 con 10k |
| 2026-11-04 | FTS5 indexa `topic_key` y `anchor_path` (`SCHEMA_VERSION=3`) | El topic es el asa estable que el agente recuerda y la ruta del ancla es lo que ve en el editor: buscar `storage/fts5` o `src/auth.py` no debe depender del título. Pesos 5/1/0.5/3/2 (título/topic/ancla/body/why). El esquema es derivado: si la versión no coincide se tira y se reconstruye |
| 2026-11-04 | El L0 muestra `[topic]` entre el `kind` y el título, y `search` lo añade al resultado | Sin él, dos memorias del mismo tema eran indistinguibles; solo ocupa caracteres en las entradas que tienen topic |
| 2026-11-04 | El drop por cambio de esquema solo actúa con `user_version` 1 o 2, nunca con 0 | Una DB recién creada sigue en 0 hasta el primer rebuild: si otro `Store` la abre a la vez y tira las tablas, el `save` concurrente falla con `no such table: mem` (visto en CI macOS) |
| 2026-11-04 | `search` consulta proyecto y scope personal y entrelaza por posición de ranking | El agente no sabe si lo que busca es decisión del repo o costumbre suya, y una búsqueda fallida le hacía duplicar la memoria. Un BM25 de otra base no es comparable, pero el primero de cada scope sí: se alternan proyectos/personal y el límite se aplica al conjunto |
| 2026-11-04 | `context` carga el último resumen del proyecto, no el más reciente de ambos scopes | La sesión personal pertenece a otro repo: meterla como "la última sesión" daba continuidad falsa. El resumen personal se sigue guardando y listando con `--personal` |
| 2026-11-06 | La cola rasgada del JSONL se repara antes del append: si el fragmento es JSON válido se le añade el `\n`; si no, se trunca | Un crash a mitad de `os.write` dejaba una línea sin salto; el siguiente `save` pegaba su evento detrás y el `rebuild` fallaba con `JSONDecodeError` en una línea intermedia, dejando el Store inutilizable en cada apertura |
| 2026-11-06 | `_append` compara la huella completa `(size, mtime_ns)` previa al append, no solo el tamaño | Un reemplazo externo del mismo tamaño (`git checkout`/`cp`) dejaba la huella vieja certificada y los eventos remotos no se indexaban hasta el siguiente rebuild manual |
| 2026-11-06 | Se rechazan tokens con prefijo de proveedor (`ghp_`, `github_pat_`, `glpat-`, `sk-proj-`, `sk-ant-`, `AIza`) | El patrón `clave = valor` no ve un token que aparece suelto en el texto; son credenciales de alta confianza y prefijo inequívoco |
| 2026-11-06 | `id` debe ser 12 hex en minúscula; `topic_key` ≤ 100 caracteres y sin controles; `render` colapsa id/title/topic al leer | Un salto de línea en el topic inyectaba líneas falsas en `MEMORY.md`; un topic de 4000 caracteres dejaba el L0 en el título. La defensa en lectura cubre ficheros ya contaminados por eventos externos |
| 2026-11-06 | Una línea del JSONL con JSON válido pero semánticamente inválida (sin `op`, `kind` fuera de enum) falla el `rebuild` en voz alta; no se ignora | Es la fuente de verdad: saltarla en silencio ocultaría memorias corruptas. La cola rasgada de un crash sí se tolera porque es una escritura incompleta, no un dato inventado |
| 2026-11-07 | Publicada la v0.7.0 en PyPI (wheel + sdist) | S5: un `save` tras un crash ya no rompe el rebuild, un replace externo del mismo tamaño se detecta y las credenciales con prefijo se rechazan. Instalación limpia desde PyPI verificada (init, save, search, session); el token y la cola rasgada se comprobaron sobre el wheel publicado |
