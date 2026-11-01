-- cairn-mem schema v1 — DERIVADO. La verdad vive en .cairn/events.jsonl.
-- Si user_version no coincide con el del código: borrar cairn.db y rebuild (automático).
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS mem (
  id          TEXT PRIMARY KEY,            -- 12 hex aleatorios (secrets.token_hex(6))
  ts          INTEGER NOT NULL,            -- time_ns; orden de aplicación en rebuild
  kind        TEXT NOT NULL CHECK (kind IN ('decision','convention','gotcha','fact')),
  topic_key   TEXT,                        -- clave estable: mismo topic = reemplaza
  title       TEXT NOT NULL,
  body        TEXT NOT NULL CHECK (length(body) <= 500),
  why         TEXT,
  anchor_path TEXT,                        -- ruta POSIX relativa a la raíz del proyecto
  anchor_hash TEXT,                        -- sha1 del contenido con CRLF→LF
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','archived'))
);
-- "stale" NO se persiste: se calcula al leer comparando anchor_hash con el archivo actual.

CREATE UNIQUE INDEX IF NOT EXISTS ux_mem_topic_active
  ON mem(topic_key) WHERE status = 'active' AND topic_key IS NOT NULL;

-- huella del JSONL para saber si la DB está al día (p. ej. tras un git pull)
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);  -- jsonl_size, jsonl_mtime_ns

CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(
  title, body, why, content='mem', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON mem BEGIN
  INSERT INTO mem_fts(rowid, title, body, why) VALUES (new.rowid, new.title, new.body, new.why);
END;
CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON mem BEGIN
  INSERT INTO mem_fts(mem_fts, rowid, title, body, why) VALUES ('delete', old.rowid, old.title, old.body, old.why);
END;
CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON mem BEGIN
  INSERT INTO mem_fts(mem_fts, rowid, title, body, why) VALUES ('delete', old.rowid, old.title, old.body, old.why);
  INSERT INTO mem_fts(rowid, title, body, why) VALUES (new.rowid, new.title, new.body, new.why);
END;
