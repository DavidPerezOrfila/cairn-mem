"""Tests de sesiones (M6): append-only, lectura y tolerancia a línea rasgada."""

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


def test_unknown_session_returns_none(tmp_path):
    assert Sessions(str(tmp_path)).get("000000000000") is None


@pytest.mark.parametrize("secret", ["password = hunter2", "AKIAIOSFODNN7EXAMPLE"])
def test_secret_in_summary_is_rejected(tmp_path, secret):
    sessions = Sessions(str(tmp_path))
    with pytest.raises(ValueError, match="secreto"):
        sessions.save(f"## Goal\nconfig {secret}")
    assert not sessions.path.exists()
