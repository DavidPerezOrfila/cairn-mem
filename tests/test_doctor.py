"""Tests de `cairn doctor`: diagnóstico local, sin red y sin crear el store."""

import json
import os
import sqlite3

import pytest

from cairn_mem.cli import main


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


def test_doctor_ok_on_a_healthy_store(capsys):
    run(capsys, "init")
    run(capsys, "save", "--kind", "fact", "--title", "t", "--body", "b")

    code, out, _ = run(capsys, "doctor")

    assert code == 0
    assert "ok    sqlite" in out
    assert "ok    events" in out and "1 eventos" in out
    assert "ok    anchors" in out


def test_doctor_json_lists_every_check(capsys):
    run(capsys, "init")

    code, out, _ = run(capsys, "doctor", "--json")

    checks = json.loads(out)
    assert code == 0
    names = [item["check"] for item in checks]
    for expected in (
        "sqlite",
        "install",
        "store",
        "gitignore",
        "events",
        "sessions",
        "db",
        "l0",
        "anchors",
    ):
        assert expected in names
    assert all(item["status"] in ("ok", "warn", "fail") for item in checks)


def test_doctor_fails_without_a_store_and_creates_nothing(capsys, in_tmp):
    code, out, _ = run(capsys, "doctor")

    assert code == 1 and "cairn init" in out
    assert not (in_tmp / ".cairn").exists()


def test_doctor_personal_does_not_create_the_home(capsys, in_tmp):
    code, out, _ = run(capsys, "doctor", "--personal")

    assert code == 1 and "--personal" in out
    assert not (in_tmp / "home").exists()


def test_doctor_does_not_create_a_missing_cairn_dir(capsys, in_tmp, monkeypatch):
    """`CAIRN_DIR` no comprueba existencia: doctor no puede inventarse el store."""
    target = in_tmp / "inventado" / ".cairn"
    monkeypatch.setenv("CAIRN_DIR", str(target))

    code, out, _ = run(capsys, "doctor")

    assert code == 1 and "cairn init" in out
    assert not target.exists()


def test_doctor_reports_a_non_object_session_line(capsys, in_tmp):
    run(capsys, "init")
    run(capsys, "session", "save", "--summary", "recap")
    path = in_tmp / ".cairn" / "sessions.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "[1]\n", encoding="utf-8")

    code, out, _ = run(capsys, "doctor")

    assert code == 1 and "sessions.jsonl línea 2" in out


def test_doctor_warns_on_an_outdated_schema(capsys, in_tmp):
    run(capsys, "init")
    conn = sqlite3.connect(str(in_tmp / ".cairn" / "cairn.db"))
    conn.execute("PRAGMA user_version = 2")
    conn.close()

    code, out, _ = run(capsys, "doctor")

    assert code == 0 and "esquema 2" in out


def test_doctor_reports_a_corrupt_event_line(capsys, in_tmp):
    run(capsys, "init")
    (in_tmp / ".cairn" / "events.jsonl").write_text('{"op":"save"}\n', encoding="utf-8")

    code, out, _ = run(capsys, "doctor")

    assert code == 1 and "línea 1" in out


def test_doctor_warns_about_missing_gitignore_entries(capsys, in_tmp):
    run(capsys, "init")
    (in_tmp / ".cairn" / ".gitignore").write_text(
        "cairn.db\nMEMORY.md\n", encoding="utf-8"
    )

    code, out, _ = run(capsys, "doctor")

    assert code == 0 and "warn  gitignore" in out and ".MEMORY.md.*" in out


def test_doctor_counts_stale_anchors(capsys, in_tmp):
    run(capsys, "init")
    (in_tmp / "a.py").write_text("v1\n", encoding="utf-8")
    run(
        capsys,
        "save",
        "--kind",
        "gotcha",
        "--title",
        "G",
        "--body",
        "x",
        "--anchor",
        "a.py",
    )
    (in_tmp / "a.py").write_text("v2\n", encoding="utf-8")

    code, out, _ = run(capsys, "doctor")

    assert code == 0 and "1 stale" in out


def test_doctor_warns_about_two_installations(capsys, in_tmp, monkeypatch):
    run(capsys, "init")
    folders = [in_tmp / "bin-a", in_tmp / "bin-b"]
    for folder in folders:
        folder.mkdir()
        for name in ("cairn", "cairn.exe"):
            target = folder / name
            target.write_text("", encoding="utf-8")
            os.chmod(target, 0o755)
    monkeypatch.setenv("PATH", os.pathsep.join(str(folder) for folder in folders))

    code, out, _ = run(capsys, "doctor")

    assert code == 0 and "2 instalaciones" in out


def test_doctor_fails_when_the_l0_exceeds_the_budget(capsys, in_tmp):
    run(capsys, "init")
    (in_tmp / ".cairn" / "MEMORY.md").write_text("x" * 3001, encoding="utf-8")

    code, out, _ = run(capsys, "doctor")

    assert code == 1 and "3001/3000" in out
