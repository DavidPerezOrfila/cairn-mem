"""Tests de sesiones (M6): append-only, lectura y tolerancia a línea rasgada."""

import json

import pytest

from cairn_mem.sessions import Sessions


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


def test_last_finds_a_recap_longer_than_the_read_window(tmp_path):
    """MAX_SUMMARY (20k) con escapes JSON supera los 64 KB: el último recap no
    puede perderse por tamaño de ventana."""
    sessions = Sessions(str(tmp_path))
    sessions.save("primera", ts=1)
    big = sessions.save("\x01" * 19_999, ts=2)
    assert sessions.last()["id"] == big


def test_save_repairs_a_long_unterminated_tail(tmp_path):
    """La reparación de cola no puede truncar un recap válido de más de 64 KB."""
    sessions = Sessions(str(tmp_path))
    raw = json.dumps(
        {"op": "session", "id": "ffffffffffff", "ts": 1, "summary": "\x01" * 19_999}
    ).encode("utf-8")
    assert len(raw) > 64 * 1024
    sessions.path.parent.mkdir(parents=True, exist_ok=True)
    sessions.path.write_bytes(raw)  # sin '\n' final

    second = sessions.save("segunda")

    assert sessions.get("ffffffffffff")["summary"].startswith("\x01")
    assert sessions.get(second)["summary"] == "segunda"


def test_unknown_session_returns_none(tmp_path):
    assert Sessions(str(tmp_path)).get("000000000000") is None


@pytest.mark.parametrize("secret", ["password = hunter2", "AKIAIOSFODNN7EXAMPLE"])
def test_secret_in_summary_is_rejected(tmp_path, secret):
    sessions = Sessions(str(tmp_path))
    with pytest.raises(ValueError, match="secreto"):
        sessions.save(f"## Goal\nconfig {secret}")
    assert not sessions.path.exists()
