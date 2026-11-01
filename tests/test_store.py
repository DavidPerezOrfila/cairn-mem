"""Tests rojos de M1 (TDD). Deben fallar hasta implementar Store."""
import json
import threading

import pytest

from cairn_mem.store import Store


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / ".cairn")


@pytest.fixture
def store(root):
    return Store(root)


def test_save_and_get(store):
    mid = store.save(kind="decision", title="Usar FTS5", body="BM25 sin vectores", why="latencia")
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
    store.save(kind="gotcha", title="OAuth callback", body="redirect_uri debe coincidir")
    r = store.search("oauth", limit=5)
    assert r and set(r[0]) >= {"id", "kind", "title", "snippet"}


@pytest.mark.parametrize("q", ["oauth-callback", "ora_ebs:vendor", 'say "hi', "NEAR", "a*b", ""])
def test_search_never_raises_on_special_chars(store, q):
    store.save(kind="gotcha", title="OAuth callback", body="redirect_uri ORA_EBS vendor")
    store.search(q)  # no debe lanzar excepción


def test_search_falls_back_from_and_to_or(store):
    store.save(kind="fact", title="Pipeline KNIME", body="carga nocturna de ventas")
    assert store.search("knime inexistente")  # AND vacío -> OR encuentra


def test_body_over_500_chars_rejected(store):
    with pytest.raises(ValueError):
        store.save(kind="fact", title="largo", body="x" * 501)


@pytest.mark.parametrize("secret", [
    "AKIAIOSFODNN7EXAMPLE",
    "-----BEGIN RSA PRIVATE KEY-----",
    "password = hunter2",
    "postgres://user:pass@host/db",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc",
])
def test_secret_rejected_and_not_written(store, root, secret):
    with pytest.raises(ValueError):
        store.save(kind="fact", title="t", body=f"config {secret}")
    import os
    p = os.path.join(root, "events.jsonl")
    assert (not os.path.exists(p)) or secret not in open(p, encoding="utf-8").read()


def test_external_append_is_picked_up(root):
    """Simula `git pull`: otro proceso añade una línea al JSONL."""
    s1 = Store(root)
    s1.save(kind="fact", title="local", body="a")
    line = {"op": "save", "id": "ffffffffffff", "ts": 9_999_999_999_999_999_999, "kind": "fact",
            "title": "remota", "body": "b"}
    with open(f"{root}/events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    s2 = Store(root)
    assert s2.get("ffffffffffff")["title"] == "remota"


def test_unicode_roundtrip_utf8_without_bom(store, root):
    mid = store.save(kind="convention", title="Convención de nombres ñ", body="usar español: áéíóú")
    assert store.get(mid)["title"] == "Convención de nombres ñ"
    raw = open(f"{root}/events.jsonl", "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "Convención".encode("utf-8") in raw  # ensure_ascii=False


def test_concurrent_appends_keep_jsonl_valid(root):
    def work(i):
        s = Store(root)
        for j in range(5):
            s.save(kind="fact", title=f"t{i}-{j}", body="b")
    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    lines = open(f"{root}/events.jsonl", encoding="utf-8").read().splitlines()
    assert len(lines) == 20 and all(json.loads(l)["op"] == "save" for l in lines)
    s = Store(root)
    s.rebuild()
    assert len([m for m in s.dump() if m["status"] == "active"]) == 20
