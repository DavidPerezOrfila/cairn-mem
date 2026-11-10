"""Tests de M1: Store (events.jsonl + SQLite FTS5)."""

import json
import os
import threading
from pathlib import Path

import pytest

from cairn_mem.store import Store, search_scopes


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / ".cairn")


@pytest.fixture
def store(root):
    return Store(root)


def _append_event(root, **event):
    """Escribe un evento por fuera del Store, como otro proceso o `git pull`."""
    with open(Path(root) / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def test_save_and_get(store):
    mid = store.save(
        kind="decision", title="Usar FTS5", body="BM25 sin vectores", why="latencia"
    )
    m = store.get(mid)
    assert m["title"] == "Usar FTS5" and m["status"] == "active"


def test_topic_key_upsert_supersedes_previous(store):
    a = store.save(kind="convention", topic_key="db/naming", title="v1", body="a")
    b = store.save(kind="convention", topic_key="db/naming", title="v2", body="b")
    assert store.get(a)["status"] == "superseded"
    assert store.get(b)["status"] == "active"


def test_archive(store):
    mid = store.save(kind="fact", title="x", body="y")
    store.archive(mid)
    assert store.get(mid)["status"] == "archived"
    assert store.search("x") == []


def test_rebuild_from_jsonl_is_identical(store):
    store.save(kind="fact", title="x", body="y")
    store.save(kind="gotcha", topic_key="t", title="a", body="b")
    store.save(kind="gotcha", topic_key="t", title="a2", body="b2")
    before = store.dump()
    store.rebuild()
    assert store.dump() == before


def test_search_returns_l1_shape(store):
    store.save(
        kind="gotcha", title="OAuth callback", body="redirect_uri debe coincidir"
    )
    r = store.search("oauth", limit=5)
    assert r and set(r[0]) >= {"id", "kind", "title", "snippet"}


@pytest.mark.parametrize(
    "q", ["oauth-callback", "ora_ebs:vendor", 'say "hi', "NEAR", "a*b", ""]
)
def test_search_never_raises_on_special_chars(store, q):
    store.save(
        kind="gotcha", title="OAuth callback", body="redirect_uri ORA_EBS vendor"
    )
    store.search(q)  # no debe lanzar excepción


def test_search_falls_back_from_and_to_or(store):
    store.save(kind="fact", title="Pipeline KNIME", body="carga nocturna")
    store.save(kind="fact", title="Informe de ventas", body="carga por turno")
    titles = {row["title"] for row in store.search("knime carga ventas")}
    assert titles == {"Pipeline KNIME", "Informe de ventas"}  # AND vacío, dos raíces


def test_search_matches_singular_and_plural(store):
    store.save(
        kind="decision",
        title="Rotacion de refresh token JWT",
        body="rotar en cada uso",
    )
    assert [row["title"] for row in store.search("token")] == [
        "Rotacion de refresh token JWT"
    ]
    assert [row["title"] for row in store.search("tokens")] == [
        "Rotacion de refresh token JWT"
    ]
    store.save(
        kind="gotcha",
        title="Magic links",
        body="caducidad de 10 minutos",
        why="el enlace reenviado sigue vivo",
    )
    assert [row["title"] for row in store.search("enlaces")] == ["Magic links"]


def test_search_ignores_stopwords(store):
    store.save(
        kind="fact", title="Puerto de Vite", body="5173 para el servidor de desarrollo"
    )
    assert store.search("el de la") == []
    assert [
        row["title"] for row in store.search("el puerto del servidor de desarrollo")
    ] == ["Puerto de Vite"]


def test_body_over_500_chars_rejected(store):
    with pytest.raises(ValueError):
        store.save(kind="fact", title="largo", body="x" * 501)


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAIOSFODNN7EXAMPLE",
        "-----BEGIN RSA PRIVATE KEY-----",
        "password = hunter2",
        "password: hunter2",
        '{"api_key": "abc123"}',
        "secret: s3cr3t",
        "DB_PASSWORD=p4ss",
        "api-key: k123",
        "private_key: abc",
        "postgres://user:pass@host/db",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc",
    ],
)
def test_secret_rejected_and_not_written(store, root, secret):
    with pytest.raises(ValueError):
        store.save(kind="fact", title="t", body=f"config {secret}")
    import os

    p = os.path.join(root, "events.jsonl")
    content = ""
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            content = f.read()
    assert secret not in content


def test_external_append_is_picked_up(root):
    """Simula `git pull`: otro proceso añade una línea al JSONL."""
    s1 = Store(root)
    s1.save(kind="fact", title="local", body="a")
    line = {
        "op": "save",
        "id": "ffffffffffff",
        "ts": 9_999_999_999_999_999_999,
        "kind": "fact",
        "title": "remota",
        "body": "b",
    }
    with open(f"{root}/events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    s2 = Store(root)
    assert s2.get("ffffffffffff")["title"] == "remota"


def test_unicode_roundtrip_utf8_without_bom(store, root):
    mid = store.save(
        kind="convention", title="Convención de nombres ñ", body="usar español: áéíóú"
    )
    assert store.get(mid)["title"] == "Convención de nombres ñ"
    with open(f"{root}/events.jsonl", "rb") as f:
        raw = f.read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "Convención".encode() in raw  # ensure_ascii=False


def test_concurrent_appends_keep_jsonl_valid(root):
    def work(i):
        s = Store(root)
        for j in range(5):
            s.save(kind="fact", title=f"t{i}-{j}", body="b")

    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    with open(f"{root}/events.jsonl", encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert len(lines) == 20 and all(json.loads(l)["op"] == "save" for l in lines)
    s = Store(root)
    s.rebuild()
    assert len([m for m in s.dump() if m["status"] == "active"]) == 20


def test_rebuild_ignores_torn_last_line(root):
    """Un crash a mitad de os.write no debe dejar el Store inutilizable."""
    s = Store(root)
    mid = s.save(kind="fact", title="ok", body="b")
    with open(f"{root}/events.jsonl", encoding="utf-8") as f:
        first = f.read().splitlines()[0]
    with open(f"{root}/events.jsonl", "w", encoding="utf-8") as f:
        f.write(first + "\n" + first[:8])
    assert Store(root).get(mid)["title"] == "ok"


def test_bom_in_events_file_is_tolerated(root):
    Store(root).save(kind="fact", title="ok", body="b")
    with open(f"{root}/events.jsonl", "rb") as f:
        raw = f.read()
    with open(f"{root}/events.jsonl", "wb") as f:
        f.write(b"\xef\xbb\xbf" + raw)
    assert Store(root).search("ok")


def test_save_with_id_updates_and_reactivates(store):
    mid = store.save(kind="fact", title="v1", body="a")
    store.archive(mid)
    store.save(kind="fact", title="v2", body="b", id=mid)
    assert store.get(mid)["title"] == "v2"
    assert store.get(mid)["status"] == "active"


def test_out_of_order_save_keeps_newest_active(store, monkeypatch):
    newer = store.save(kind="fact", topic_key="t", title="nuevo", body="b")
    monkeypatch.setattr("cairn_mem.store.time.time_ns", lambda: 1)
    older = store.save(kind="fact", topic_key="t", title="viejo", body="b")
    assert store.get(newer)["status"] == "active"
    assert store.get(older)["status"] == "superseded"


@pytest.mark.parametrize("limit", [0, -1])
def test_search_non_positive_limit_returns_empty(store, limit):
    store.save(kind="fact", title="x", body="y")
    assert store.search("x", limit=limit) == []


@pytest.mark.parametrize("field", ["topic_key", "anchor_path"])
def test_secret_in_metadata_rejected(store, root, field):
    with pytest.raises(ValueError):
        store.save(kind="fact", title="t", body="b", **{field: "password = hunter2"})
    path = f"{root}/events.jsonl"
    content = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            content = f.read()
    assert "hunter2" not in content


def test_events_jsonl_uses_lf(store, root):
    store.save(kind="fact", title="x", body="y")
    with open(f"{root}/events.jsonl", "rb") as f:
        raw = f.read()
    assert b"\r\n" not in raw and raw.endswith(b"\n")


def test_external_append_between_saves_is_not_lost(root):
    s = Store(root)
    s.save(kind="fact", title="uno", body="a")
    external = {
        "op": "save",
        "id": "dddddddddddd",
        "ts": 2,
        "kind": "fact",
        "title": "externa",
        "body": "b",
    }
    with open(f"{root}/events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(external, ensure_ascii=False) + "\n")
    s.save(kind="fact", title="dos", body="c")
    assert s.get("dddddddddddd")["title"] == "externa"


def test_external_append_during_apply_triggers_rebuild(root, monkeypatch):
    """La huella se captura tras el append, no tras el apply."""
    s = Store(root)
    original_apply = s._apply
    external = {
        "op": "save",
        "id": "eeeeeeeeeeee",
        "ts": 1,
        "kind": "fact",
        "title": "externa",
        "body": "b",
    }

    def apply_then_inject(event):
        original_apply(event)
        with open(f"{root}/events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(external, ensure_ascii=False) + "\n")

    monkeypatch.setattr(s, "_apply", apply_then_inject)
    s.save(kind="fact", title="local", body="a")
    assert Store(root).get("eeeeeeeeeeee")["title"] == "externa"


def test_consecutive_saves_do_not_rebuild(store, monkeypatch):
    monkeypatch.setattr(store, "rebuild", lambda: pytest.fail("rebuild inesperado"))
    store.save(kind="fact", title="uno", body="a")
    store.save(kind="fact", title="dos", body="b")
    assert len(store.dump()) == 2


def test_long_lived_store_sees_external_append_on_read(root):
    """El Store del MCP vive horas: una lectura no debe servir datos viejos."""
    s = Store(root)
    s.save(kind="fact", title="local", body="a")
    external = {
        "op": "save",
        "id": "cccccccccccc",
        "ts": 2,
        "kind": "fact",
        "title": "remota",
        "body": "b",
    }
    with open(f"{root}/events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(external, ensure_ascii=False) + "\n")
    assert s.get("cccccccccccc")["title"] == "remota"
    assert s.search("remota")[0]["id"] == "cccccccccccc"


def test_long_lived_store_sees_external_archive_on_read(root):
    s = Store(root)
    mid = s.save(kind="fact", title="local", body="a")
    with open(f"{root}/events.jsonl", "a", encoding="utf-8") as f:
        f.write(
            json.dumps({"op": "archive", "id": mid, "ts": 9_999_999_999_999_999_999})
            + "\n"
        )
    assert s.get(mid)["status"] == "archived"
    assert s.search("local") == []


def test_reads_do_not_rebuild_when_nothing_changed(store, monkeypatch):
    mid = store.save(kind="fact", title="x", body="y")
    monkeypatch.setattr(store, "rebuild", lambda: pytest.fail("rebuild inesperado"))
    assert store.get(mid) and store.search("x") and store.active_ordered()


def test_active_ordered_interleaves_kinds_and_respects_limit(store):
    for index in range(4):
        store.save(kind="decision", title=f"d{index}", body="x")
        store.save(kind="gotcha", title=f"g{index}", body="x")
    rows = store.active_ordered(limit=3)
    assert [row["kind"] for row in rows] == ["decision", "gotcha", "decision"]


def test_title_is_normalized_and_bounded(store):
    mid = store.save(kind="fact", title="uno\ndos", body="x")
    assert store.get(mid)["title"] == "uno dos"
    with pytest.raises(ValueError, match="title"):
        store.save(kind="fact", title="x" * 201, body="x")
    with pytest.raises(ValueError, match="vacío"):
        store.save(kind="fact", title="   ", body="x")


def test_out_of_range_topic_saves_keep_append_order(root):
    s = Store(root)
    old = s.save(kind="fact", topic_key="t", title="viejo", body="a", ts=2**63 - 1)
    new = s.save(kind="fact", topic_key="t", title="nuevo", body="b", ts=2**63 + 5)
    s.rebuild()
    assert s.get(new)["status"] == "active"
    assert s.get(old)["status"] == "superseded"


def test_archive_unknown_id_is_a_noop(root):
    s = Store(root)
    s.archive("000000000000")
    assert s.get("000000000000") is None


def test_rebuild_does_not_certify_events_written_during_it(root, monkeypatch):
    """Un append externo a mitad del rebuild no puede darse por aplicado."""
    s = Store(root)
    s.save(kind="fact", title="local", body="a")
    injected = []

    def apply_then_inject(event):
        Store._apply(s, event)
        if not injected:
            injected.append(True)
            with open(f"{root}/events.jsonl", "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "op": "save",
                            "id": "aaaaaaaaaaaa",
                            "ts": 9_999_999_999_999_999_998,
                            "kind": "fact",
                            "title": "externa",
                            "body": "b",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    monkeypatch.setattr(s, "_apply", apply_then_inject)
    s.rebuild()
    assert s.get("aaaaaaaaaaaa")["title"] == "externa"


def test_short_write_rolls_back_and_keeps_jsonl_valid(root, monkeypatch):
    s = Store(root)
    s.save(kind="fact", title="ok", body="a")
    path = Path(root) / "events.jsonl"
    size = path.stat().st_size
    monkeypatch.setattr("cairn_mem.jsonl.os.write", lambda fd, data: 1)
    with pytest.raises(OSError, match="incompleta"):
        s.save(kind="fact", title="falla", body="b")
    assert path.stat().st_size == size
    assert Store(root).search("ok")


def test_write_error_rolls_back_and_keeps_jsonl_valid(root, monkeypatch):
    s = Store(root)
    s.save(kind="fact", title="ok", body="a")
    path = Path(root) / "events.jsonl"
    size = path.stat().st_size

    def fail(fd, data):
        raise OSError("ENOSPC")

    monkeypatch.setattr("cairn_mem.jsonl.os.write", fail)
    with pytest.raises(OSError):
        s.save(kind="fact", title="falla", body="b")
    assert path.stat().st_size == size
    assert Store(root).search("ok")


def test_archive_survives_rebuild_with_future_save(root):
    s = Store(root)
    mid = s.save(kind="fact", title="futuro", body="a", ts=9_999_999_999_999_999_999)
    s.archive(mid)
    s.rebuild()
    assert s.get(mid)["status"] == "archived"
    assert s.search("futuro") == []


def test_l0_failure_warns_instead_of_silence(store, monkeypatch, capsys):
    def locked(*args, **kwargs):
        raise OSError("archivo bloqueado")

    monkeypatch.setattr("cairn_mem.store.os.replace", locked)
    mid = store.save(kind="fact", title="visible", body="b")
    assert mid
    assert "MEMORY.md" in capsys.readouterr().err


def test_l0_regenerated_after_archive_and_rebuild(store, root):
    mid = store.save(kind="fact", title="visible", body="b")
    memory = Path(root) / "MEMORY.md"
    assert "visible" in memory.read_text(encoding="utf-8")
    store.archive(mid)
    assert "visible" not in memory.read_text(encoding="utf-8")
    store.rebuild()
    assert "visible" not in memory.read_text(encoding="utf-8")


def test_search_by_topic_key(store):
    mid = store.save(
        kind="decision",
        topic_key="infra/deploy",
        title="Pipeline ETL",
        body="carga nocturna de ventas",
    )
    assert [row["id"] for row in store.search("infra deploy")] == [mid]


def test_search_by_anchor_path(store):
    mid = store.save(
        kind="gotcha",
        title="OAuth callback",
        body="redirect_uri exacto",
        anchor_path="src/auth.py",
    )
    assert [row["id"] for row in store.search("src/auth")] == [mid]


def test_search_result_exposes_topic_key(store):
    mid = store.save(
        kind="decision", topic_key="storage/fts5", title="Usar FTS5", body="bm25"
    )
    without = store.save(kind="fact", title="Sin topic", body="bm25")
    rows = {row["id"]: row for row in store.search("bm25")}
    assert rows[mid]["topic_key"] == "storage/fts5"
    assert rows[without]["topic_key"] is None


def test_search_scopes_interleaves_scopes_by_rank(tmp_path):
    project = Store(str(tmp_path / "project"))
    personal = Store(str(tmp_path / "personal"))
    for title in ("uno", "dos", "tres"):
        project.save(kind="fact", title=f"fts5 {title}", body="bm25")
    for title in ("alfa", "beta"):
        personal.save(kind="fact", title=f"fts5 {title}", body="bm25")

    rows = search_scopes(project, personal, "fts5", limit=5)
    assert [row["scope"] for row in rows] == [
        "project",
        "personal",
        "project",
        "personal",
        "project",
    ]
    assert [row["title"] for row in rows if row["scope"] == "personal"] == [
        "fts5 alfa",
        "fts5 beta",
    ]


def test_search_scopes_applies_limit_to_merged(tmp_path):
    project = Store(str(tmp_path / "project"))
    personal = Store(str(tmp_path / "personal"))
    project.save(kind="fact", title="fts5 proyecto", body="bm25")
    personal.save(kind="fact", title="fts5 personal", body="bm25")

    rows = search_scopes(project, personal, "fts5", limit=1)
    assert [(row["scope"], row["title"]) for row in rows] == [
        ("project", "fts5 proyecto")
    ]


def test_search_scopes_without_personal(tmp_path):
    project = Store(str(tmp_path / "project"))
    project.save(kind="fact", title="fts5 solo", body="bm25")
    rows = search_scopes(project, None, "fts5")
    assert [(row["scope"], row["title"]) for row in rows] == [("project", "fts5 solo")]


def test_schema_2_is_rebuilt_and_topic_becomes_searchable(root):
    """Una DB de 0.3.x (schema 2) se reconstruye sola al abrirla."""
    import sqlite3

    Path(root).mkdir(parents=True, exist_ok=True)
    (Path(root) / "events.jsonl").write_text(
        json.dumps(
            {
                "op": "save",
                "id": "aaaaaaaabbbb",
                "ts": 1,
                "kind": "decision",
                "topic_key": "storage/fts5",
                "title": "Usar FTS5",
                "body": "bm25",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(str(Path(root) / "cairn.db"))
    conn.executescript(
        """
        CREATE TABLE mem (
          id TEXT PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL,
          topic_key TEXT, title TEXT NOT NULL, body TEXT NOT NULL, why TEXT,
          anchor_path TEXT, anchor_hash TEXT, status TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE mem_fts USING fts5(
          title, body, why, content='mem', content_rowid='rowid'
        );
        PRAGMA user_version = 2;
        """
    )
    conn.close()

    store = Store(root)
    assert [row["id"] for row in store.search("storage")] == ["aaaaaaaabbbb"]


def test_save_after_torn_tail_repairs_jsonl(root):
    """La cola rasgada no puede pegarse al siguiente evento (P0 auditoría)."""
    s = Store(root)
    mid = s.save(kind="fact", title="ok", body="a")
    path = Path(root) / "events.jsonl"
    path.write_bytes(path.read_bytes() + b'{"op":"save","id":"')

    s.save(kind="fact", title="posterior", body="b")

    for line in path.read_text(encoding="utf-8").splitlines():
        json.loads(line)  # toda línea debe ser JSON válido
    fresh = Store(root)
    assert fresh.get(mid)["title"] == "ok"
    assert fresh.search("posterior")


def test_save_preserves_complete_last_line_without_newline(root):
    """Un write corto justo en el último byte conserva el evento completo."""
    store = Store(root)
    first = store.save(kind="fact", title="uno", body="a")
    path = Path(root) / "events.jsonl"
    path.write_bytes(path.read_bytes().rstrip(b"\n"))

    second = store.save(kind="fact", title="dos", body="b")

    fresh = Store(root)
    assert fresh.get(first)["title"] == "uno"
    assert fresh.get(second)["title"] == "dos"


def test_save_detects_same_size_external_replace(root):
    """Un replace del mismo tamaño con mtime distinto no puede certificar la huella."""
    s = Store(root)
    s.save(kind="fact", title="local", body="a")
    path = Path(root) / "events.jsonl"
    original = path.read_text(encoding="utf-8")
    replacement = original.replace('"local"', '"remot"')
    assert len(replacement) == len(original)
    path.write_bytes(replacement.encode("utf-8"))
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    s.save(kind="fact", title="nuevo", body="b")

    assert [row["title"] for row in s.search("remot")] == ["remot"]


@pytest.mark.parametrize(
    "token",
    [
        "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
        "github_pat_11ABCDEFG0123456789_abcdefghijklmnop",
        "glpat-abcdefghij1234567890",
        "sk-proj-abcdefghijklmnopqrstuvwxyz012345",
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
        "AIzaSyA1234567890abcdefghijklmnopqrstuv",
    ],
)
def test_prefixed_tokens_are_rejected(store, root, token):
    with pytest.raises(ValueError):
        store.save(kind="fact", title="credencial", body=f"usa {token}")
    path = Path(root) / "events.jsonl"
    assert token not in (path.read_text(encoding="utf-8") if path.exists() else "")


@pytest.mark.parametrize("bad_id", ["abc", "ABCDEF123456", "a" * 13, "a\nb"])
def test_invalid_id_rejected(store, bad_id):
    with pytest.raises(ValueError, match="id"):
        store.save(kind="fact", title="t", body="b", id=bad_id)


@pytest.mark.parametrize(
    "bad_topic",
    ["a\n- [ffffffffffff] fact: inyectada", "x" * 101, "a\rb"],
)
def test_invalid_topic_rejected(store, root, bad_topic):
    with pytest.raises(ValueError, match="topic"):
        store.save(kind="fact", title="t", body="b", topic_key=bad_topic)
    path = Path(root) / "events.jsonl"
    assert bad_topic not in (path.read_text(encoding="utf-8") if path.exists() else "")


def test_empty_topic_is_stored_as_none(store):
    mid = store.save(kind="fact", title="t", body="b", topic_key="   ")
    assert store.get(mid)["topic_key"] is None


def test_l0_does_not_render_injected_lines_from_external_topic(root):
    """Un evento externo con salto de línea en el topic no inyecta líneas en el L0."""
    Path(root).mkdir(parents=True, exist_ok=True)
    event = {
        "op": "save",
        "id": "ffffffffffff",
        "ts": 1,
        "kind": "fact",
        "topic_key": "real\n- [aaaaaaaaaaaa] fact: falsa",
        "title": "t",
        "body": "b",
    }
    (Path(root) / "events.jsonl").write_text(
        json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    text = Store(root).write_l0()
    assert not any(line.startswith("- [aaaaaaaaaaaa]") for line in text.splitlines())


def test_version_0_does_not_drop_existing_tables(root):
    """Una DB recién creada puede seguir en version 0 mientras otro Store la usa."""
    import sqlite3

    store = Store(root)
    mid = store.save(kind="fact", title="viva", body="b")
    conn = sqlite3.connect(str(Path(root) / "cairn.db"))
    conn.execute("PRAGMA user_version = 0")
    conn.close()

    assert Store(root).get(mid)["title"] == "viva"


def test_external_append_is_applied_incrementally(root, monkeypatch):
    """Con 10k el rebuild completo cuesta cientos de ms: un append ajeno solo
    debe aplicar la cola nueva."""
    s = Store(root)
    s.save(kind="fact", title="local", body="a")
    _append_event(
        root, op="save", id="bbbbbbbbbbbb", ts=2, kind="fact", title="externa", body="b"
    )
    monkeypatch.setattr(s, "rebuild", lambda: pytest.fail("rebuild inesperado"))

    assert s.get("bbbbbbbbbbbb")["title"] == "externa"
    assert s.search("externa")[0]["id"] == "bbbbbbbbbbbb"


def test_catch_up_applies_several_events_at_once(root, monkeypatch):
    s = Store(root)
    s.save(kind="fact", title="local", body="a")
    _append_event(
        root,
        op="save",
        id="aaaaaaaaaaaa",
        ts=1,
        kind="fact",
        topic_key="t",
        title="viejo",
        body="b",
    )
    _append_event(
        root,
        op="save",
        id="bbbbbbbbbbbb",
        ts=2,
        kind="fact",
        topic_key="t",
        title="nuevo",
        body="b",
    )
    monkeypatch.setattr(s, "rebuild", lambda: pytest.fail("rebuild inesperado"))

    assert s.get("aaaaaaaaaaaa")["status"] == "superseded"
    assert s.get("bbbbbbbbbbbb")["status"] == "active"


def test_external_update_of_existing_id_rebuilds(root, monkeypatch):
    """Un update o un archive dependen del orden global por ts: rebuild."""
    s = Store(root)
    mid = s.save(kind="fact", title="v1", body="a")
    calls = []
    original = s.rebuild
    monkeypatch.setattr(s, "rebuild", lambda: (calls.append(1), original())[1])
    _append_event(
        root,
        op="save",
        id=mid,
        ts=9_999_999_999_999_999_999,
        kind="fact",
        title="v2",
        body="b",
    )

    assert s.get(mid)["title"] == "v2"
    assert calls == [1]


def test_truncated_jsonl_triggers_rebuild(root, monkeypatch):
    s = Store(root)
    first = s.save(kind="fact", title="uno", body="a")
    second = s.save(kind="fact", title="dos", body="b")
    path = Path(root) / "events.jsonl"
    path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
    calls = []
    original = s.rebuild
    monkeypatch.setattr(s, "rebuild", lambda: (calls.append(1), original())[1])

    assert s.get(first)["title"] == "uno"
    assert s.get(second) is None
    assert calls == [1]


def test_catch_up_survives_torn_tail(root):
    s = Store(root)
    s.save(kind="fact", title="local", body="a")
    path = Path(root) / "events.jsonl"
    path.write_bytes(path.read_bytes() + b'{"op":"save"')
    assert s.search("local")[0]["title"] == "local"

    second = Store(root).save(kind="fact", title="dos", body="b")

    assert s.get(second)["title"] == "dos"


def test_catch_up_matches_rebuild(root, monkeypatch):
    s = Store(root)
    s.save(kind="fact", title="local", body="a")
    for index in range(5):
        _append_event(
            root,
            op="save",
            id=f"{index + 1:012x}",
            ts=10 + index,
            kind="fact",
            topic_key=f"t{index % 2}",
            title=f"externa {index}",
            body="b",
        )
    monkeypatch.setattr(s, "rebuild", lambda: pytest.fail("rebuild inesperado"))

    s.search("local")

    fresh = Store(root)
    assert [(row["id"], row["status"]) for row in s.dump()] == [
        (row["id"], row["status"]) for row in fresh.dump()
    ]


def test_catch_up_does_not_certify_events_written_during_it(root, monkeypatch):
    """La huella se captura antes de leer: lo que llegue a mitad se aplica luego."""
    s = Store(root)
    s.save(kind="fact", title="local", body="a")
    _append_event(
        root, op="save", id="aaaaaaaaaaaa", ts=2, kind="fact", title="primera", body="b"
    )
    original = s._apply
    injected = []

    def apply_then_inject(event):
        original(event)
        if not injected:
            injected.append(True)
            _append_event(
                root,
                op="save",
                id="bbbbbbbbbbbb",
                ts=3,
                kind="fact",
                title="segunda",
                body="b",
            )

    monkeypatch.setattr(s, "_apply", apply_then_inject)
    assert s.get("aaaaaaaaaaaa")["title"] == "primera"
    monkeypatch.setattr(s, "_apply", original)
    assert s.get("bbbbbbbbbbbb")["title"] == "segunda"


def test_save_does_not_certify_a_prefix_replaced_while_hashing(root, monkeypatch):
    """Un replace ajeno que cae entre el append y el sha1 del prefijo no puede
    certificar bytes que este Store nunca aplicó: el offset guardado tiene que
    ser el del fichero que de verdad se indexó."""
    s = Store(root)
    s.save(kind="fact", title="local", body="a")
    dense = (",", ":")
    real = Store._prefix_hash
    swapped = []

    def replace_then_hash(self, offset):
        source = Path(root) / "events.jsonl"
        if not swapped and b'"nueva"' in source.read_bytes():
            # nuestro append ya está; el replace llega durante el sha1
            swapped.append(True)
            head = json.dumps(
                {
                    "op": "save",
                    "id": "cccccccccccc",
                    "ts": 9,
                    "kind": "fact",
                    "title": "ajena",
                    "body": "",
                },
                ensure_ascii=False,
                separators=dense,
            )
            padding = offset - len(head.encode("utf-8")) - 1
            assert padding > 0
            head = head.replace('"body":""', f'"body":"{"x" * padding}"') + "\n"
            assert len(head.encode("utf-8")) == offset
            tail = (
                json.dumps(
                    {
                        "op": "save",
                        "id": "bbbbbbbbbbbb",
                        "ts": 10,
                        "kind": "fact",
                        "title": "cola",
                        "body": "b",
                    },
                    ensure_ascii=False,
                    separators=dense,
                )
                + "\n"
            )
            source.write_bytes((head + tail).encode("utf-8"))
        return real(self, offset)

    monkeypatch.setattr(Store, "_prefix_hash", replace_then_hash)

    s.save(kind="fact", title="nueva", body="c")

    assert swapped, "el test no llegó a simular el replace"
    mirror = Path(root).parent / "espejo" / ".cairn"
    mirror.mkdir(parents=True)
    (mirror / "events.jsonl").write_bytes((Path(root) / "events.jsonl").read_bytes())
    assert [(row["id"], row["title"]) for row in s.dump()] == [
        (row["id"], row["title"]) for row in Store(str(mirror)).dump()
    ]
    assert s.get("bbbbbbbbbbbb")["title"] == "cola"
