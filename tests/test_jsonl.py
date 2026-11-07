"""Tests de la reparación de cola del JSONL antes de cada append."""

import json

from cairn_mem.jsonl import append_jsonl

EVENT = {
    "op": "save",
    "id": "aaaaaaaaaaaa",
    "ts": 1,
    "kind": "fact",
    "title": "primera",
    "body": "b",
}
OTHER = {
    "op": "save",
    "id": "bbbbbbbbbbbb",
    "ts": 2,
    "kind": "fact",
    "title": "segunda",
    "body": "d",
}


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_complete_line_without_newline_is_preserved(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(json.dumps(EVENT).encode("utf-8"))

    append_jsonl(path, OTHER)

    assert [line["id"] for line in _lines(path)] == [EVENT["id"], OTHER["id"]]


def test_valid_json_non_object_fragment_is_truncated(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(json.dumps(EVENT).encode("utf-8") + b"\n[1,2]")

    append_jsonl(path, OTHER)

    assert [line["id"] for line in _lines(path)] == [EVENT["id"], OTHER["id"]]


def test_fragment_over_the_cap_is_truncated(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"x" * (64 * 1024 + 1))

    append_jsonl(path, OTHER)

    assert [line["id"] for line in _lines(path)] == [OTHER["id"]]
