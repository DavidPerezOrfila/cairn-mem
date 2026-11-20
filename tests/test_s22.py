"""Tests de S22: keywords en el FTS, history de un topic y appends multiproceso."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cairn_mem.cli import main
from cairn_mem.store import Store, parse_event


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / ".cairn")


@pytest.fixture
def store(root):
    return Store(root)


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAIRN_DIR", raising=False)
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "home"))
    return tmp_path


def run(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def _append_event(root, **event):
    with open(Path(root) / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# --- keywords ---


def test_keywords_find_the_memory_by_its_synonyms(store):
    mid = store.save(
        kind="convention",
        title="Cifrado de secretos en reposo",
        body="la clave vive en el gestor y se rota cada trimestre",
        keywords="contraseñas guardar almacenar",
    )
    assert [row["id"] for row in store.search("contraseñas")] == [mid]


def test_without_keywords_the_synonym_does_not_match(store):
    store.save(
        kind="convention",
        title="Cifrado de secretos en reposo",
        body="la clave vive en el gestor y se rota cada trimestre",
    )
    assert store.search("contraseñas") == []


def test_keywords_survive_rebuild_and_reopen(store, root):
    mid = store.save(
        kind="convention",
        title="Vistas Oracle",
        body="nombres en mayúsculas",
        keywords="objetos BD nombrar",
    )
    store.rebuild()
    assert Store(root).get(mid)["keywords"] == "objetos BD nombrar"
    assert [row["id"] for row in store.search("nombrar")] == [mid]


def test_keywords_are_normalized_and_empty_becomes_none(store):
    mid = store.save(kind="fact", title="t", body="b", keywords="  uno   dos  ")
    assert store.get(mid)["keywords"] == "uno dos"
    other = store.save(kind="fact", title="u", body="c", keywords="   ")
    assert store.get(other)["keywords"] is None


@pytest.mark.parametrize("bad", ["a\nb", "a\rb", "x" * 201])
def test_keywords_validated_at_write(store, bad):
    with pytest.raises(ValueError, match="keywords"):
        store.save(kind="fact", title="t", body="b", keywords=bad)


@pytest.mark.parametrize("bad", [7, "a\nb", "x" * 201])
def test_parse_event_rejects_bad_keywords(root, bad):
    Path(root).mkdir(parents=True, exist_ok=True)
    (Path(root) / "events.jsonl").touch()
    _append_event(
        root,
        op="save",
        id="aaaaaaaabbbb",
        ts=1,
        kind="fact",
        title="t",
        body="b",
        keywords=bad,
    )
    with pytest.raises(ValueError):
        Store(root)


def test_parse_event_accepts_keywords():
    event = {
        "op": "save",
        "id": "aaaaaaaabbbb",
        "ts": 1,
        "kind": "fact",
        "title": "t",
        "body": "b",
        "keywords": "uno dos",
    }
    assert parse_event(json.dumps(event), 0)["keywords"] == "uno dos"


def test_cli_save_keywords(capsys, store):
    code, out, _ = run(
        capsys,
        "save",
        "--kind",
        "convention",
        "--title",
        "Cifrado de secretos",
        "--body",
        "la clave vive en el gestor",
        "--keywords",
        "contraseñas guardar",
    )
    assert code == 0
    mid = out.strip()
    assert store.get(mid)["keywords"] == "contraseñas guardar"
    assert run(capsys, "search", "contraseñas", "--json")[1]


def test_mcp_save_keywords(in_tmp):
    from cairn_mem.mcp import Server

    (in_tmp / ".cairn").mkdir(exist_ok=True)
    (in_tmp / ".cairn" / "events.jsonl").touch()
    server = Server()
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "save",
                "arguments": {
                    "kind": "fact",
                    "title": "t",
                    "body": "b",
                    "keywords": "sinonimo",
                },
            },
        }
    )
    mid = response["result"]["content"][0]["text"].splitlines()[0]
    assert server.store().get(mid)["keywords"] == "sinonimo"


PARAPHRASE = Path(__file__).resolve().parents[1] / "bench" / "paraphrase.jsonl"


def test_paraphrase_gate_does_not_regress(tmp_path):
    """Gate de S22: el set duro de paráfrasis queda en Hit@3 1.00 con keywords.
    `bench/paraphrase.jsonl` es la referencia; si baja, el cambio de ranking no
    entra."""
    entries = [
        json.loads(line)
        for line in PARAPHRASE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    corpus = [entry for entry in entries if "title" in entry]
    queries = [entry for entry in entries if "query" in entry]
    root = tmp_path / ".cairn"
    root.mkdir()
    lines = []
    for index, memory in enumerate(corpus):
        event = {
            "op": "save",
            "id": f"{index:012x}",
            "ts": 1_700_000_000_000_000_000 + index,
            "kind": memory["kind"],
            "title": memory["title"],
            "body": memory["body"],
        }
        for key in ("why", "keywords"):
            if memory.get(key):
                event[key] = memory[key]
        lines.append(json.dumps(event, ensure_ascii=False))
    (root / "events.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    store = Store(str(root))
    try:
        misses = [
            (query["id"], query["query"])
            for query in queries
            if not set(query["expect"])
            & {row["title"] for row in store.search(query["query"], limit=3)}
        ]
    finally:
        store.close()
    assert not misses


# --- history ---


def test_history_lists_every_version_with_its_status(store):
    first = store.save(kind="decision", topic_key="db/naming", title="v1", body="a")
    second = store.save(kind="decision", topic_key="db/naming", title="v2", body="b")
    store.archive(second)
    rows = store.history("db/naming")
    assert [(row["id"], row["status"]) for row in rows] == [
        (first, "superseded"),
        (second, "archived"),
    ]


def test_history_of_unknown_topic_is_empty(store):
    store.save(kind="fact", title="t", body="b")
    assert store.history("no/existe") == []


def test_cli_history_json_includes_scope(capsys, store):
    store.save(kind="decision", topic_key="db/naming", title="v1", body="a")
    store.save(kind="decision", topic_key="db/naming", title="v2", body="b")
    code, out, _ = run(capsys, "history", "db/naming", "--json")
    assert code == 0
    rows = json.loads(out)
    assert [row["status"] for row in rows] == ["superseded", "active"]
    assert rows[0]["scope"] == "project"


def test_cli_history_unknown_topic_is_not_an_error(capsys, store):
    store.save(kind="fact", title="t", body="b")
    code, out, _ = run(capsys, "history", "no/existe")
    assert code == 0 and "no history" in out


# --- append multiproceso ---

WORKERS = 8
ROUNDS = 25
APPEND_SCRIPT = """
import sys
from pathlib import Path
from cairn_mem.jsonl import append_jsonl

path, worker = Path(sys.argv[1]), int(sys.argv[2])
for index in range(__ROUNDS__):
    append_jsonl(
        path,
        {
            "op": "save",
            "id": f"{worker:06d}{index:06d}",
            "ts": worker * 1000 + index,
            "kind": "fact",
            "title": f"worker {worker} {index}",
            "body": "b",
        },
    )
""".replace("__ROUNDS__", str(ROUNDS))


def test_eight_processes_append_valid_lines(tmp_path):
    """`jsonl._LOCK` solo serializa hilos: 8 procesos deben dejar 200 líneas
    JSON completas, sin que `_repair_tail` trunque una línea a medias."""
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"basura')  # cola rasgada: el primer proceso la repara
    source = str(Path(__file__).resolve().parents[1] / "src")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [source, os.environ.get("PYTHONPATH", "")]
        ).strip(os.pathsep),
    }
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", APPEND_SCRIPT, str(path), str(worker)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for worker in range(WORKERS)
    ]
    try:
        for process in processes:
            _, err = process.communicate(timeout=120)
            assert process.returncode == 0, err.decode(errors="replace")
    finally:
        for process in processes:
            if process.poll() is None:  # timeout o fallo: no dejar huérfanos
                process.kill()
                process.wait()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == WORKERS * ROUNDS
    events = [json.loads(line) for line in lines]
    assert len({event["id"] for event in events}) == WORKERS * ROUNDS

    root = tmp_path / ".cairn"
    root.mkdir()
    (root / "events.jsonl").write_bytes(path.read_bytes())
    store = Store(str(root))
    try:
        assert len(store.dump()) == WORKERS * ROUNDS
    finally:
        store.close()


def test_pin_keeps_keywords(store):
    mid = store.save(kind="fact", title="t", body="b", keywords="uno dos")
    store.pin(mid)
    assert store.get(mid)["keywords"] == "uno dos"
    assert store.get(mid)["pinned"] == 1


def test_doctor_flags_a_secret_stored_in_keywords(root):
    from cairn_mem.doctor import run as doctor_run

    Path(root).mkdir(parents=True, exist_ok=True)
    _append_event(
        root,
        op="save",
        id="abcdefabcdef",
        ts=1,
        kind="fact",
        title="t",
        body="b",
        keywords="AKIAIOSFODNN7EXAMPLE",
    )
    checks = doctor_run(Path(root))
    assert any(
        item["status"] == "fail" and item["check"] == "secrets" for item in checks
    )


def test_history_keeps_superseded_rows_after_rebuild(root):
    store = Store(root)
    first = store.save(kind="decision", topic_key="db/naming", title="v1", body="a")
    second = store.save(kind="decision", topic_key="db/naming", title="v2", body="b")
    store.rebuild()
    rows = Store(root).history("db/naming")
    assert [row["id"] for row in rows] == [first, second]
    assert [row["status"] for row in rows] == ["superseded", "active"]


def test_cli_history_labels_the_personal_scope(capsys, store):
    store.save(kind="decision", topic_key="db/naming", title="proyecto", body="a")
    code, _, _ = run(
        capsys,
        "save",
        "--kind",
        "decision",
        "--title",
        "personal",
        "--body",
        "b",
        "--topic",
        "db/naming",
        "--personal",
    )
    assert code == 0
    code, out, _ = run(capsys, "history", "db/naming")
    assert code == 0 and "[personal]" in out and "proyecto" in out
    code, out, _ = run(capsys, "history", "db/naming", "--json")
    scopes = sorted(row["scope"] for row in json.loads(out))
    assert scopes == ["personal", "project"]
