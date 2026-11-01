"""Tests de la CLI (M1): init, save, search, get, archive, rebuild."""

import hashlib
import json

import pytest

from cairn_mem.cli import main


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAIRN_DIR", raising=False)
    return tmp_path


def run(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_init_local_only_by_default(capsys, in_tmp):
    code, out, _ = run(capsys, "init")
    assert code == 0 and ".cairn" in out
    assert (in_tmp / ".cairn" / "events.jsonl").exists()
    ignore = (in_tmp / ".cairn" / ".gitignore").read_text(encoding="utf-8")
    assert "events.jsonl" in ignore


def test_init_share_tracks_events(capsys, in_tmp):
    run(capsys, "init", "--share")
    ignore = (in_tmp / ".cairn" / ".gitignore").read_text(encoding="utf-8")
    assert "events.jsonl" not in ignore


def test_save_search_get_json(capsys):
    run(capsys, "init")
    code, out, _ = run(
        capsys,
        "save",
        "--kind",
        "gotcha",
        "--title",
        "OAuth callback",
        "--body",
        "redirect_uri debe coincidir",
        "--json",
    )
    mid = json.loads(out)["id"]
    assert code == 0 and len(mid) == 12

    code, out, _ = run(capsys, "search", "oauth", "--json")
    assert code == 0 and json.loads(out)[0]["id"] == mid

    code, out, _ = run(capsys, "get", mid, "--json")
    assert json.loads(out)["title"] == "OAuth callback"


def test_search_text_output(capsys):
    run(capsys, "init")
    run(
        capsys,
        "save",
        "--kind",
        "fact",
        "--title",
        "Pipeline KNIME",
        "--body",
        "carga nocturna",
    )
    code, out, _ = run(capsys, "search", "knime")
    assert code == 0 and "Pipeline KNIME" in out


def test_archive_hides_from_search(capsys):
    run(capsys, "init")
    _, out, _ = run(
        capsys, "save", "--kind", "fact", "--title", "x", "--body", "y", "--json"
    )
    mid = json.loads(out)["id"]
    assert run(capsys, "archive", mid)[0] == 0
    assert run(capsys, "search", "x")[0] == 0
    assert "x" not in run(capsys, "search", "x")[1]


def test_get_unknown_id_fails(capsys):
    run(capsys, "init")
    code, _, err = run(capsys, "get", "000000000000")
    assert code == 1 and "no existe" in err


def test_commands_require_init(capsys, in_tmp):
    code, _, err = run(capsys, "search", "x")
    assert code == 1 and "cairn init" in err


def test_cairn_dir_override(capsys, in_tmp, monkeypatch, tmp_path_factory):
    other = tmp_path_factory.mktemp("memoria")
    monkeypatch.setenv("CAIRN_DIR", str(other / ".cairn"))
    run(capsys, "init")
    code, _, _ = run(
        capsys, "save", "--kind", "fact", "--title", "t", "--body", "b", "--json"
    )
    assert code == 0 and (other / ".cairn" / "events.jsonl").exists()


def test_secret_rejected_by_cli(capsys, in_tmp):
    run(capsys, "init")
    code, _, err = run(
        capsys, "save", "--kind", "fact", "--title", "t", "--body", "password = hunter2"
    )
    assert code == 1 and "secreto" in err
    raw = (in_tmp / ".cairn" / "events.jsonl").read_text(encoding="utf-8")
    assert "hunter2" not in raw


def test_save_anchor_hashes_lf(capsys, in_tmp):
    run(capsys, "init")
    (in_tmp / "a.py").write_bytes(b"x\r\ny\r\n")
    _, out, _ = run(
        capsys,
        "save",
        "--kind",
        "gotcha",
        "--title",
        "t",
        "--body",
        "b",
        "--anchor",
        "a.py",
        "--json",
    )
    mid = json.loads(out)["id"]
    _, out, _ = run(capsys, "get", mid, "--json")
    stored = json.loads(out)
    assert stored["anchor_path"] == "a.py"
    assert stored["anchor_hash"] == hashlib.sha1(b"x\ny\n").hexdigest()


def test_absolute_anchor_is_stored_relative(capsys, in_tmp):
    run(capsys, "init")
    target = in_tmp / "src" / "a.py"
    target.parent.mkdir()
    target.write_text("x\n", encoding="utf-8")
    _, out, _ = run(
        capsys,
        "save",
        "--kind",
        "gotcha",
        "--title",
        "t",
        "--body",
        "b",
        "--anchor",
        str(target),
        "--json",
    )
    mid = json.loads(out)["id"]
    _, out, _ = run(capsys, "get", mid, "--json")
    assert json.loads(out)["anchor_path"] == "src/a.py"
