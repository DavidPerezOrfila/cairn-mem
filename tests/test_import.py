"""Tests del importador legacy (M8): mapeo, routing e idempotencia."""

import json
import sqlite3

import pytest

from cairn_mem.cli import main
from cairn_mem.legacy import _ts, import_legacy
from cairn_mem.store import Store

SCHEMA = """
CREATE TABLE observations (
  id INTEGER PRIMARY KEY,
  sync_id TEXT,
  type TEXT,
  title TEXT,
  content TEXT,
  project TEXT,
  scope TEXT,
  topic_key TEXT,
  deleted_at TEXT,
  superseded_by_sync_id TEXT,
  created_at TEXT
);
CREATE TABLE capture_project_provenance (
  entity_kind TEXT,
  entity_id TEXT,
  source TEXT,
  directory TEXT,
  raw_project TEXT
);
"""


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAIRN_DIR", raising=False)
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "personal"))
    return tmp_path


@pytest.fixture
def legacy_db(tmp_path):
    repo = tmp_path
    other = tmp_path / "other"
    other.mkdir()
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    rows = [
        (
            1,
            "decision",
            "Usar FTS5",
            "**What**: elegimos FTS5\n**Why**: sin dependencias\n**Where**: store.py",
            "repo",
            "project",
            "db/fts",
            None,
            None,
            "2026-11-01 10:00:00",
            str(repo),
        ),
        (
            2,
            "config",
            "Modelo global",
            "What: deepseek\nWhy: preferencia del usuario",
            "repo",
            "global",
            "config/model",
            None,
            None,
            "2026-11-01 11:00:00",
            str(repo),
        ),
        (
            3,
            "session_summary",
            "Session summary: repo",
            "## Goal\nCerrar M6",
            "repo",
            "project",
            None,
            None,
            None,
            "2026-11-01 12:00:00",
            str(repo),
        ),
        (
            4,
            "decision",
            "Borrada",
            "x",
            "repo",
            "project",
            None,
            "2026-11-02 00:00:00",
            None,
            "2026-11-01 13:00:00",
            str(repo),
        ),
        (
            5,
            "decision",
            "Superseded",
            "x",
            "repo",
            "project",
            "t",
            None,
            "sync-1",
            "2026-11-01 14:00:00",
            str(repo),
        ),
        (
            6,
            "fact",
            "Secreto",
            "password = hunter2",
            "repo",
            "project",
            None,
            None,
            None,
            "2026-11-01 15:00:00",
            str(repo),
        ),
        (
            7,
            "discovery",
            "Otro repo",
            "x",
            "otro",
            "project",
            None,
            None,
            None,
            "2026-11-01 16:00:00",
            str(other),
        ),
        (
            8,
            "fact",
            "Cuerpo largo",
            "**What**: " + "a" * 600,
            "repo",
            "project",
            None,
            None,
            None,
            "2026-11-01 17:00:00",
            str(repo),
        ),
    ]
    conn.executemany(
        "INSERT INTO observations (id, type, title, content, project, scope, "
        "topic_key, deleted_at, superseded_by_sync_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [row[:10] for row in rows],
    )
    conn.executemany(
        "INSERT INTO capture_project_provenance "
        "(entity_kind, entity_id, source, directory, raw_project) "
        "VALUES ('observation', ?, 'unknown', ?, '')",
        [(str(row[0]), row[10]) for row in rows],
    )
    conn.commit()
    conn.close()
    return path


def _init(capsys, repo):
    code = main(["init"])
    assert code == 0
    assert (repo / ".cairn" / "events.jsonl").exists()


def test_import_maps_and_routes(capsys, in_tmp, legacy_db):
    repo = in_tmp
    _init(capsys, repo)
    report = import_legacy(str(legacy_db))
    assert report == {
        "memories": 3,
        "sessions": 1,
        "skipped": 0,
        "rejected": 1,
        "dry_run": False,
    }

    rows = {row["title"]: row for row in Store(str(repo / ".cairn")).dump()}
    assert rows["Usar FTS5"]["kind"] == "decision"
    assert rows["Usar FTS5"]["body"] == "elegimos FTS5"
    assert rows["Usar FTS5"]["why"] == "Why: sin dependencias | Where: store.py"
    assert rows["Cuerpo largo"]["body"] == "a" * 500
    assert "Secreto" not in rows and "Otro repo" not in rows

    personal = Store(str(in_tmp / "personal"))
    global_row = personal.search("modelo")[0]
    assert global_row["title"] == "Modelo global"
    assert global_row["kind"] == "decision"
    assert personal.get(global_row["id"])["topic_key"] == "repo/config/model"

    sessions = (repo / ".cairn" / "sessions.jsonl").read_text(encoding="utf-8")
    assert "Cerrar M6" in sessions
    l0 = (repo / ".cairn" / "MEMORY.md").read_text(encoding="utf-8")
    assert "Usar FTS5" in l0 and "Modelo global" not in l0


def test_import_is_idempotent(capsys, in_tmp, legacy_db):
    repo = in_tmp
    _init(capsys, repo)
    import_legacy(str(legacy_db))
    report = import_legacy(str(legacy_db))
    assert report["memories"] == 0 and report["sessions"] == 0
    assert report["skipped"] == 4 and report["rejected"] == 1
    assert len(Store(str(repo / ".cairn")).dump()) == 2


def test_dry_run_writes_nothing(capsys, in_tmp, legacy_db):
    repo = in_tmp
    (repo / ".cairn").mkdir(parents=True)
    report = import_legacy(str(legacy_db), dry_run=True)
    assert report["memories"] == 3 and report["sessions"] == 1
    assert not (repo / ".cairn" / "events.jsonl").exists()
    assert not (in_tmp / "personal").exists()


def test_ts_normalizes_nanoseconds_and_timezone():
    assert _ts("2026-11-01 10:00:00.123456789") == _ts("2026-11-01 10:00:00.123456")
    assert _ts("2026-11-01 10:00:00.1") == _ts("2026-11-01 10:00:00.100000")
    assert _ts("2026-11-01 10:00:00.123") == _ts("2026-11-01 10:00:00.123000")
    assert _ts("2026-11-01T10:00:00Z") == _ts("2026-11-01 10:00:00")


def test_import_normalizes_long_and_empty_titles(capsys, in_tmp):
    repo = in_tmp
    _init(capsys, repo)
    path = in_tmp / "otra.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    rows = [
        (1, "fact", "x" * 400, "**What**: cuerpo", "repo", "project"),
        (2, "fact", "   ", "**What**: sin título", "repo", "project"),
    ]
    conn.executemany(
        "INSERT INTO observations (id, type, title, content, project, scope) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO capture_project_provenance "
        "(entity_kind, entity_id, source, directory, raw_project) "
        "VALUES ('observation', ?, 'unknown', ?, '')",
        [(str(row[0]), str(repo)) for row in rows],
    )
    conn.commit()
    conn.close()
    report = import_legacy(str(path))
    assert report["memories"] == 2 and report["rejected"] == 0
    titles = {row["title"] for row in Store(str(repo / ".cairn")).dump()}
    assert "x" * 200 in titles
    assert "sin título" in titles


def test_cli_import_requires_db(capsys, in_tmp):
    with pytest.raises(SystemExit):
        main(["import", "legacy"])


def test_cli_import_json(capsys, in_tmp, legacy_db):
    repo = in_tmp
    _init(capsys, repo)
    capsys.readouterr()
    code = main(["import", "legacy", "--db", str(legacy_db), "--dry-run", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["dry_run"] is True and report["memories"] == 3
