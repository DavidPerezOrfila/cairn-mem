"""Tests de la reparación de cola del JSONL antes de cada append."""

import json
import os

from cairn_mem.jsonl import _lock, _open_lock, _unlock, append_jsonl

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


def test_lock_does_not_block_reading_the_log(tmp_path):
    """El lock va en `events.jsonl.lock`: bloquear byte 0 del log impedía leerlo
    (Windows devuelve PermissionError) y el `rebuild` de otro proceso fallaba
    mientras alguien escribía."""
    path = tmp_path / "events.jsonl"
    append_jsonl(path, EVENT)
    lock_fd = _open_lock(path)
    try:
        _lock(lock_fd)
        assert path.read_bytes().endswith(b"\n")
    finally:
        _unlock(lock_fd)
        os.close(lock_fd)
