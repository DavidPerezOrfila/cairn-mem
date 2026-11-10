"""Tests de sesiones (M6): append-only, lectura y tolerancia a línea rasgada."""

import json

import pytest

from cairn_mem import sessions as sessions_module
from cairn_mem.sessions import MAX_SUMMARY, Sessions


def test_save_and_get_long_summary(tmp_path):
    sessions = Sessions(str(tmp_path))
    summary = "## Goal\nCerrar M6\n\n" + "detalle " * 1000
    sid = sessions.save(summary)
    assert len(sid) == 12
    assert sessions.get(sid)["summary"].startswith("## Goal")


def test_list_latest_first_and_limit(tmp_path):
    sessions = Sessions(str(tmp_path))
    first = sessions.save("uno", ts=1)
    second = sessions.save("dos", ts=2)
    assert [record["id"] for record in sessions.all()] == [second, first]
    assert [record["id"] for record in sessions.all(limit=1)] == [second]


def test_list_orders_equal_timestamps_by_append_order(tmp_path):
    sessions = Sessions(str(tmp_path))
    first = sessions.save("primera", id="ffffffffffff", ts=1)
    second = sessions.save("segunda", id="000000000000", ts=1)
    assert [record["id"] for record in sessions.all()] == [second, first]


def test_corrupt_tail_is_ignored(tmp_path):
    sessions = Sessions(str(tmp_path))
    sid = sessions.save("ok")
    with open(sessions.path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"op":"session"')
    assert [record["id"] for record in sessions.all()] == [sid]


def test_save_after_torn_tail_keeps_both_sessions(tmp_path):
    """Un crash a mitad de write no puede hacer que el siguiente save rompa el replay."""
    sessions = Sessions(str(tmp_path))
    first = sessions.save("primera")
    with open(sessions.path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"op":"session","id":"')
    second = sessions.save("segunda")

    fresh = Sessions(str(tmp_path))
    assert fresh.get(first)["summary"] == "primera"
    assert fresh.get(second)["summary"] == "segunda"


def test_empty_summary_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="vacío"):
        Sessions(str(tmp_path)).save("   ")


def test_last_returns_the_newest_and_skips_a_torn_line(tmp_path):
    sessions = Sessions(str(tmp_path))
    assert sessions.last() is None
    sessions.save("primera", ts=1)
    second = sessions.save("segunda", ts=2)
    with open(sessions.path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"op":"session"')
    assert sessions.last()["id"] == second


def test_last_reads_a_long_file_without_loading_it(tmp_path):
    """El último recap se busca en la cola: 5k recaps no se parsean enteros."""
    sessions = Sessions(str(tmp_path))
    for number in range(500):
        sessions.save("linea " * 100, ts=number)
    last = sessions.save("última", ts=10_000)
    assert sessions.last()["id"] == last


def _line(**event):
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def test_last_finds_a_recap_near_the_character_cap(tmp_path):
    """`MAX_SUMMARY` son caracteres y el fichero bytes: 20k emojis son 80 KB.

    Con una ventana de 64 KB el registro más nuevo no cabía, y `last()` devolvía
    el recap anterior: la sesión siguiente arrancaba con la continuidad de dos
    sesiones antes, sin ningún aviso.
    """
    sessions = Sessions(str(tmp_path))
    first = sessions.save("primera", ts=1)
    big = sessions.save("🎉" * MAX_SUMMARY)
    assert sessions.path.stat().st_size > 64 * 1024
    assert sessions.last()["id"] == big
    assert sessions.last()["id"] != first


def test_last_widens_the_window_until_the_record_fits(tmp_path, monkeypatch):
    """Un recap escrito por fuera del límite tampoco puede ocultar la última sesión."""
    monkeypatch.setattr(sessions_module, "RECORD_WINDOW", 16)
    store = Sessions(str(tmp_path))
    store.save("una", ts=1)
    last = store.save("dos " * 200, ts=2)
    assert store.last()["id"] == last


def test_last_keeps_a_record_that_starts_at_the_window_edge(tmp_path, monkeypatch):
    """La primera línea de la ventana es entera cuando el corte cae tras un `\\n`."""
    path = tmp_path / "sessions.jsonl"
    first = _line(op="session", id="aaaaaaaaaaaa", ts=1, summary="primera")
    second = _line(op="session", id="bbbbbbbbbbbb", ts=2, summary="segunda")
    path.write_bytes(first + second)
    monkeypatch.setattr(sessions_module, "RECORD_WINDOW", len(second))
    assert sessions_module.Sessions(str(tmp_path)).last()["id"] == "bbbbbbbbbbbb"


@pytest.mark.parametrize("limit", [0, -2])
def test_list_rejects_a_non_positive_limit(tmp_path, limit):
    sessions = Sessions(str(tmp_path))
    sessions.save("uno", ts=1)
    sessions.save("dos", ts=2)
    with pytest.raises(ValueError, match="1 o más"):
        sessions.all(limit=limit)


def test_unknown_session_returns_none(tmp_path):
    assert Sessions(str(tmp_path)).get("000000000000") is None


@pytest.mark.parametrize("secret", ["password = hunter2", "AKIAIOSFODNN7EXAMPLE"])
def test_secret_in_summary_is_rejected(tmp_path, secret):
    sessions = Sessions(str(tmp_path))
    with pytest.raises(ValueError, match="secreto"):
        sessions.save(f"## Goal\nconfig {secret}")
    assert not sessions.path.exists()
