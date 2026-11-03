"""Tests del servidor MCP (M5): JSON-RPC, tools y framing stdio."""

import io
import json
import subprocess
import sys

import pytest

from cairn_mem.mcp import Server, serve


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAIRN_DIR", raising=False)
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "home"))
    (tmp_path / ".cairn").mkdir()
    (tmp_path / ".cairn" / "events.jsonl").touch()
    return tmp_path


def call(server, name, **arguments):
    return server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )


def text(response):
    return response["result"]["content"][0]["text"]


def test_initialize_and_list_tools():
    server = Server()
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        }
    )
    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert response["result"]["serverInfo"]["name"] == "cairn-mem"

    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == {"save", "search", "get", "context", "save_session"}


def test_personal_scope_roundtrip(in_tmp):
    server = Server()
    memory_id = text(
        call(
            server,
            "save",
            kind="convention",
            title="Commits en LF",
            body="todos los repos",
            scope="personal",
        )
    )
    assert (in_tmp / "home" / "events.jsonl").exists()
    assert json.loads(text(call(server, "search", query="commits"))) == []
    found = json.loads(text(call(server, "search", query="commits", scope="personal")))
    assert found[0]["id"] == memory_id
    assert (
        json.loads(text(call(server, "get", id=memory_id)))["title"] == "Commits en LF"
    )


def test_session_tool_stores_summary(in_tmp):
    server = Server()
    sid = text(call(server, "save_session", summary="## Goal\nCerrar M6"))
    assert len(sid) == 12
    raw = (in_tmp / ".cairn" / "sessions.jsonl").read_text(encoding="utf-8")
    assert "Cerrar M6" in raw
    assert "Cerrar M6" not in (in_tmp / ".cairn" / "events.jsonl").read_text(
        encoding="utf-8"
    )


def test_session_tool_personal_scope(in_tmp):
    server = Server()
    text(call(server, "save_session", summary="recap global", scope="personal"))
    raw = (in_tmp / "home" / "sessions.jsonl").read_text(encoding="utf-8")
    assert "recap global" in raw


def test_get_personal_without_project_init(in_tmp):
    server = Server()
    memory_id = text(
        call(
            server, "save", kind="fact", title="Compartida", body="x", scope="personal"
        )
    )
    (in_tmp / ".cairn" / "events.jsonl").unlink()
    (in_tmp / ".cairn").rmdir()
    memory = json.loads(text(call(server, "get", id=memory_id)))
    assert memory["title"] == "Compartida"


def test_notification_has_no_response():
    server = Server()
    assert (
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    )


def test_save_search_get_roundtrip():
    server = Server()
    response = call(
        server,
        "save",
        kind="gotcha",
        title="OAuth callback",
        body="redirect_uri debe coincidir",
        why="visto en producción",
    )
    memory_id = text(response) if "result" in response else None
    assert memory_id and len(memory_id) == 12

    results = json.loads(text(call(server, "search", query="oauth")))
    assert results[0]["id"] == memory_id

    memory = json.loads(text(call(server, "get", id=memory_id)))
    assert memory["title"] == "OAuth callback"


def test_save_uses_topic_and_anchor(in_tmp):
    server = Server()
    (in_tmp / "a.py").write_text("x\n", encoding="utf-8")
    first = text(call(server, "save", kind="fact", title="A", body="v1", topic="t"))
    second = text(
        call(
            server, "save", kind="fact", title="A", body="v2", topic="t", anchor="a.py"
        )
    )
    assert first != second
    rows = {row["id"]: row for row in server.store().dump()}
    assert rows[first]["status"] == "superseded"
    assert rows[second]["status"] == "active"
    assert rows[second]["anchor_path"] == "a.py"


def test_context_returns_l0():
    server = Server()
    call(server, "save", kind="decision", title="Usar FTS5", body="bm25")
    body = text(call(server, "context"))
    assert body.startswith("# Memoria del proyecto")
    assert "Usar FTS5" in body


def test_context_includes_last_session_without_touching_l0(in_tmp):
    server = Server()
    call(server, "save", kind="decision", title="Usar FTS5", body="bm25")
    call(server, "save_session", summary="## Goal\nCerrar M9")
    body = text(call(server, "context"))
    assert "Usar FTS5" in body and "Cerrar M9" in body
    memory = (in_tmp / ".cairn" / "MEMORY.md").read_text(encoding="utf-8")
    assert "Cerrar M9" not in memory


def test_context_sees_personal_session():
    server = Server()
    call(server, "save", kind="decision", title="Usar FTS5", body="bm25")
    call(server, "save_session", summary="recap global", scope="personal")
    assert "recap global" in text(call(server, "context"))


def test_context_truncates_long_session_summary():
    server = Server()
    call(server, "save_session", summary="x" * 9000)
    body = text(call(server, "context"))
    assert "… (recortado)" in body and len(body) < 9000


def test_tool_errors_are_structured():
    server = Server()
    response = call(server, "save", kind="fact", title="t", body="password = hunter2")
    assert response["result"]["isError"] is True
    assert "secreto" in text(response)

    response = call(server, "get", id="000000000000")
    assert response["result"]["isError"] is True


def test_unknown_method_and_bad_request():
    server = Server()
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})
    assert response["error"]["code"] == -32601
    response = server.handle({"jsonrpc": "2.0", "id": 2})
    assert response["error"]["code"] == -32600
    response = call(server, "nope")
    assert response["error"]["code"] == -32602


def test_initialize_falls_back_to_supported_version():
    server = Server()
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        }
    )
    assert response["result"]["protocolVersion"] == "2025-06-18"


def test_save_rejects_anchor_outside_project(in_tmp):
    outside = in_tmp.parent / "outside.py"
    outside.write_text("x\n", encoding="utf-8")
    response = call(
        Server(),
        "save",
        kind="fact",
        title="t",
        body="b",
        anchor="../outside.py",
    )
    assert response["result"]["isError"] is True
    assert "dentro del proyecto" in text(response)


def test_serve_ndjson_and_parse_error():
    payload = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\nnot json\n\n'
    out = io.BytesIO()
    assert serve(stdin=io.BytesIO(payload), stdout=out) == 0
    lines = out.getvalue().splitlines()
    assert json.loads(lines[0])["result"] == {}
    assert json.loads(lines[1])["error"]["code"] == -32700
    assert b"\r\n" not in out.getvalue()


def test_stdio_subprocess_roundtrip(in_tmp):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "save",
                "arguments": {"kind": "fact", "title": "T", "body": "B"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": "T"}},
        },
    ]
    payload = "\n".join(json.dumps(m) for m in messages) + "\n"
    process = subprocess.run(
        [sys.executable, "-m", "cairn_mem.cli", "mcp"],
        input=payload.encode("utf-8"),
        capture_output=True,
        cwd=in_tmp,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert b"\r\n" not in process.stdout
    responses = [
        json.loads(line) for line in process.stdout.decode("utf-8").splitlines()
    ]
    assert [r["id"] for r in responses] == [1, 2, 3, 4]
    assert responses[1]["result"]["tools"]
    assert "T" in responses[3]["result"]["content"][0]["text"]


def test_mcp_without_init_returns_tool_error(in_tmp):
    (in_tmp / ".cairn" / "events.jsonl").unlink()
    (in_tmp / ".cairn").rmdir()
    server = Server()
    response = call(server, "search", query="x")
    assert response["result"]["isError"] is True
    assert "cairn init" in text(response)
