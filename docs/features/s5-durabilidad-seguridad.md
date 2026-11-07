# S5 — Durabilidad y seguridad de la fuente de verdad

**Objetivo:** cerrar los tres P0 reproducidos en la auditoría de 2026-11-06 antes de
tocar ranking o features. Un `save` no puede corromper `events.jsonl`, perder eventos
externos ni aceptar credenciales.

## Alcance

- **Cola rasgada:** un crash a mitad de `os.write` deja una línea sin `\n`. Antes de
  hacer append, `append_jsonl` repara la cola: si el fragmento es JSON válido le añade
  el `\n`; si no, lo trunca. Sin esto, el siguiente `save` pegaba su evento al
  fragmento y el `rebuild` fallaba con `JSONDecodeError` en una línea intermedia.
  Cubre `events.jsonl` y `sessions.jsonl` (comparten `append_jsonl`).
- **Reemplazo externo del mismo tamaño:** `Store._append` compara la huella completa
  `(size, mtime_ns)` previa al append contra la guardada, no solo el tamaño. Un
  `git checkout`/`cp` que cambia el contenido sin cambiar el tamaño ya no certifica una
  huella falsa: dispara `rebuild` y los eventos remotos se indexan.
- **Tokens con prefijo:** se rechazan `ghp_`, `github_pat_`, `glpat-`, `sk-proj-`,
  `sk-ant-`, `AIza` y demás prefijos de credencial (antes solo se detectaban
  `clave = valor`).
- **`id` y `topic_key` validados:** `id` debe ser 12 hex en minúscula; `topic_key` no
  puede contener caracteres de control y se acota a 100 caracteres. Un `topic` de 4000
  caracteres dejaba el L0 en el título; un salto de línea inyectaba líneas falsas en
  `MEMORY.md`. `render._line` colapsa además el topic al leer, para ficheros ya
  contaminados por eventos externos.
- El importador valida el topic en `--dry-run` igual que en la importación real.

Fuera de alcance: sincronización incremental (S7), formato del JSONL, ranking.

## Criterios de aceptación

1. Un `save` tras una cola rasgada deja el JSONL válido línea a línea y no pierde la
   memoria previa.
2. Un reemplazo externo del mismo tamaño con mtime distinto se detecta en el siguiente
   `save` y la memoria remota queda indexada.
3. Los prefijos de token listados se rechazan y no se escriben.
4. `id` no hex, `topic_key` con salto de línea o de más de 100 caracteres → `ValueError`
   y nada escrito; el L0 no admite líneas inyectadas.
5. Suite y `ruff` en verde.

## Evidencia (2026-11-07)

- `pytest -q`: **175 passed** (22 nuevos: 18 en `tests/test_store.py`, 1 en
  `tests/test_sessions.py`, 3 en `tests/test_jsonl.py`). Antes: 153.
- `ruff check src tests bench`: limpio.
- Los tests fijan el defecto: con la comparación tamaño-solo (código anterior), el
  test de replace del mismo tamaño falla (`assert [] == ['remot']`); con la huella
  completa pasa. La reparación de cola se prueba en sus tres ramas (fragmento válido
  sin `\n` conservado, JSON no-objeto truncado, fragmento > 64 KiB truncado).
- P0 reproducidos antes del cambio: (1) `events.jsonl` + `{"op":"save","id":"` sin
  salto → el siguiente `save` lanzaba `JSONDecodeError` al reconstruir; (2) replace
  del mismo tamaño con mtime distinto → `search("remot")` vacío; (3) tokens `ghp_`/
  `sk-`/`AIza` aceptados; (4) `topic` con `\n` inyectaba una línea en el L0 y uno de
  4000 caracteres dejaba el L0 en el título.
- `python bench/bench_mcp.py --reps 20` (10k): search 8,9 / save 18,6 / context
  14,3 ms p95 → **SLO < 50 ms: OK**.
- `python bench/bench_cli.py --reps 20` pareado contra v0.6.0 en la misma máquina:
  v0.6.0 1k search p95 328,4 / save 354,8 y 10k search p95 406,4 / save 389,4;
  rama 1k 368,9 / 342,9 y 10k 325,4 / 349,6; search interno 3,7 → 3,6 ms. El ruido
  de la máquina (±40 ms) domina la diferencia: **sin regresión**.
- Revisión read-only del diff (subagente): halló que el test del replace se escribía
  con `write_text`, que en Windows añade `\r\n` y cambiaba el tamaño, así que pasaba
  también con el código viejo. Corregido con `write_bytes` y verificado en rojo contra
  la comparación anterior; se añadieron los tests de las ramas de `_repair_tail`.
- **Publicación 0.7.0:** 2026-11-07 en PyPI (wheel + sdist). `pip index versions
  cairn-mem` → 0.7.0; instalación limpia en venv desde PyPI verificada con `init`,
  `save`, `search`, `session save` y `session list`. Sobre ese wheel: un token `ghp_`
  se rechaza (exit 1) y un `save` tras una cola rasgada funciona y se recupera con
  `search`. El primer `uv publish` subió 0.6.0 porque `dist/` no se había reconstruido;
  se borraron `dist/` y `build/` y se volvió a construir (lección de AGENTS.md).

