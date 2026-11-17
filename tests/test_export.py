"""Tests de `cairn export` (S16.1): memoria a Markdown para un harness sin cairn."""

import json

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


def save(capsys, *argv):
    return run(capsys, "save", *argv)


def test_export_renders_active_memories(capsys, in_tmp):
    assert run(capsys, "init")[0] == 0
    save(
        capsys,
        "--kind",
        "decision",
        "--title",
        "FTS5 over LIKE",
        "--body",
        "bm25 ranking",
        "--why",
        "escala a 10k",
        "--topic",
        "storage/fts5",
    )
    code, out, _ = run(capsys, "export")
    assert code == 0
    assert out.startswith("# Memoria cairn")
    assert "## decision" in out
    assert "### FTS5 over LIKE" in out
    assert "bm25 ranking" in out and "escala a 10k" in out
    assert "storage/fts5" in out
    assert "1 memorias activas" in out


def test_export_skips_archived_and_superseded(capsys, in_tmp):
    assert run(capsys, "init")[0] == 0
    save(capsys, "--kind", "fact", "--title", "vieja", "--body", "x", "--topic", "a/b")
    save(capsys, "--kind", "fact", "--title", "nueva", "--body", "y", "--topic", "a/b")
    save(capsys, "--kind", "gotcha", "--title", "retirada", "--body", "z")
    mid = run(capsys, "search", "retirada", "--json")[1]
    assert run(capsys, "archive", json.loads(mid)[0]["id"])[0] == 0
    out = run(capsys, "export")[1]
    assert "nueva" in out and "vieja" not in out and "retirada" not in out


def test_export_includes_sessions_on_demand(capsys, in_tmp):
    assert run(capsys, "init")[0] == 0
    for text in ("sesión uno", "sesión dos"):
        assert run(capsys, "session", "save", "--summary", text)[0] == 0
    assert "sesión uno" not in run(capsys, "export")[1]
    out = run(capsys, "export", "--sessions", "1")[1]
    assert "## sesiones" in out and "sesión dos" in out
    assert "sesión uno" not in out
    assert "## sesiones" not in run(capsys, "export", "--sessions", "-1")[1]


def test_export_out_writes_a_file(capsys, in_tmp):
    assert run(capsys, "init")[0] == 0
    save(capsys, "--kind", "fact", "--title", "algo", "--body", "x")
    target = in_tmp / "MEMORIA.md"
    code, out, _ = run(capsys, "export", "--out", str(target))
    assert code == 0 and str(target) in out
    assert "### algo" in target.read_text(encoding="utf-8")


def test_export_is_deterministic(capsys, in_tmp):
    assert run(capsys, "init")[0] == 0
    for title in ("uno", "dos", "tres"):
        save(capsys, "--kind", "fact", "--title", title, "--body", "x")
    assert run(capsys, "export")[1] == run(capsys, "export")[1]


def test_export_personal_scope(capsys, in_tmp):
    save(
        capsys,
        "--kind",
        "convention",
        "--title",
        "lf",
        "--body",
        "siempre",
        "--personal",
    )
    code, out, _ = run(capsys, "export", "--personal")
    assert code == 0 and "lf" in out
    code, _, err = run(capsys, "export")
    assert code == 1 and ".cairn" in err
