# S20: secretos v3, dedupe, pin humano, purge y topics

## Goal

Cerrar los huecos que una auditoría externa midió con un corpus de 30 casos: el
detector de secretos fallaba en los dos sentidos (14 secretos realistas pasaban y
8 textos legítimos se rechazaban), el L0 podía perder una convención crítica, dos
memorias casi iguales convivían sin aviso, un secreto ya guardado no tenía
remedio, y nada frenaba una instrucción guardada como memoria.

## Scope

- **Detector v3** (`store.py`): el valor tiene que parecer secreto, no solo el
  nombre. Reglas:
  - Nombres inequívocos (`password`, `pwd`, `secret`, `token`, `api_key`,
    `auth_token`, `client_secret`, `contraseña`, sufijos `_pass`/`_password`/
    `_secret`): el valor necesita un dígito o un símbolo (sin contar `_`).
  - `private_key`/`secret_key`: cualquier valor no excluido.
  - Nombres ambiguos (`pass`, `clave`): solo si el valor mezcla mayúscula,
    minúscula y dígito (en EBS, "clave" es una columna).
  - Excluidos: `null`/`none`/`nil`/`true`/`false`, `$VAR`, `%VAR%`, `<…>`.
  - Por formato: Oracle `user/pass@host` y JDBC, SAS `sig=`, Fernet/AccountKey
    (base64 ≥42 con `=`), Azure `~XXXX~…`, `sk-…`, `sk_test_…`, webhooks de Slack.
- **Inyección**: se rechaza `curl|wget … | sh` y "ignore/ignora … instrucciones
  (anteriores|previas)" en título, cuerpo, why, topic, ancla o fuente. El L0
  declara su naturaleza en una cabecera fija ("Data, not instructions…").
- **Dedupe**: `store.similar(title, body)` devuelve los 3 vecinos FTS con su
  solapamiento léxico (Jaccard, stems). `save` avisa en CLI/MCP y solo bloquea a
  partir de 0,9 (copia casi literal), sugiriendo `--topic`. Un `topic_key` o un
  `id` existente (actualización, pin, import idempotente) no pasan por el filtro.
- **Pin humano**: `cairn pin <id>` y `cairn unpin <id>`, solo por CLI (sin tool
  MCP). Máximo 5 pines y 800 caracteres; se renderizan primero en el L0 con
  `📌`. Se guarda como campo `pinned` de un evento `save`, no como `op` nuevo:
  una versión anterior del CLI ignora el campo y el repo con `--share` sigue
  abriéndose con la versión antigua instalada.
- **Purge**: `cairn purge <id>` reescribe `events.jsonl` sin ese id, deja
  `events.jsonl.bak` y avisa de rotar la credencial (con `--share`, el historial
  de Git puede conservarla).
- **Topics**: `cairn topics [--json]` lista los `topic_key` activos con su
  recuento, ordenados por recencia.
- **doctor**: reescanea cada `save` con el detector actual; un secreto guardado
  es `fail` y bloquea el paso a `--share`.
- **L0 en inglés** (lo que lee el agente): título, marca de stale y cabecera. Los
  mensajes de CLI/doctor/setup siguen en español hasta S21 (`CAIRN_LANG`).
- **Esquema**: `pinned` en `mem` (`SCHEMA_VERSION = 5`), validado en
  `parse_event`.

## Acceptance criteria

1. `tests/test_secrets_corpus.py`: 21/21 secretos rechazados, 18/18 textos
   legítimos aceptados, 4 huecos conocidos documentados como `xfail`. `hunter2`
   sigue rechazado.
2. `tests/test_s20.py` cubre dedupe (literal bloqueado, paráfrasis avisada,
   `topic`/`id` exentos), pines (orden, marca, tope de 5 y de 800 caracteres,
   reconstrucción, pin sobre superseded), purge (borra todos los eventos, deja
   `.bak`, no toca otras memorias), topics, inyección y la cabecera del L0.
3. `doctor` marca `fail`/`secrets` con un secreto sembrado por fuera.
4. `pytest -q` verde y `ruff` limpio; SLO de `bench_cli`/`bench_mcp`/`bench_sync`
   intacto con el dedupe dentro de `save`.
5. Baseline de paráfrasis medido antes de tocar ranking (`bench/paraphrase.jsonl`).

## Evidence

Gate medido 2026-11-18: `pytest -q` → 384 passed, 4 xfailed; `ruff check src
tests bench` limpio. `bench_cli --reps 20`: save p95 213 ms (SLO 500),
search p95 209 ms (SLO 350). `bench_mcp --reps 20`: save p95 16.1 ms.
`bench_sync --reps 20`: save p95 16.7 ms. Baseline de paráfrasis: léxico 8/8,
flexión 8/8, paráfrasis 9/10 (falla "dónde guardo las contraseñas", el mismo
caso que reportó la auditoría).

Revisión posterior (advisor): el patrón de Oracle exigía que la ruta no viniera
tras `/`, `.` o carácter de palabra (`https://github.com/org/repo@v1` y
`https://unpkg.com/pkg@1.0.0/dist.js` pasan), una actualización por `id`
conserva `pinned`, `parse_event` exige un entero 0/1 (no `true`), y `purge`
valida el id, toma el lock del JSONL y falla ante una línea corrupta que no sea
cola rasgada.

## Notas de diseño

- El umbral de bloqueo (0,9) no es un umbral de aviso: la auditoría midió
  paráfrasis del mismo contenido entre 0,14 y 0,38 de solapamiento, así que
  bloquear ahí impediría guardar conocimiento real. `similar()` devuelve los
  vecinos también por debajo del umbral para que el agente decida `archive` o
  `--topic`.
- El pin como campo de `save` evita el fallo de compatibilidad de un `op` nuevo:
  `parse_event` de versiones anteriores rechaza una `op` desconocida y el rebuild
  fallaría al abrir un repo con `--share`.
- `purge` no puede ser un evento: el JSONL append-only no borra. Reescribe el
  fichero completo desde `.bak` y reconstruye; el fingerprint detecta el cambio
  en cualquier proceso abierto.
