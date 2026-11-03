"""Tests de M1: Store (events.jsonl + SQLite FTS5)."""

import json
import os
import threading
from pathlib import Path

import pytest

from cairn_mem.store import Store


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / ".cairn")


@pytest.fixture
def store(root):
    return Store(root)


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
    store.save(kind="fact", title="Pipeline KNIME", body="carga nocturna de ventas")
    assert store.search("knime inexistente")  # AND vacío -> OR encuentra


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
