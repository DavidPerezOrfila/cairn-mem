"""Tests de la CLI (M1): init, save, search, get, archive, rebuild."""

import hashlib
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


def test_init_local_only_by_default(capsys, in_tmp):
    code, out, _ = run(capsys, "init")
    assert code == 0 and ".cairn" in out
    assert (in_tmp / ".cairn" / "events.jsonl").exists()
    ignore = (in_tmp / ".cairn" / ".gitignore").read_text(encoding="utf-8")
    assert "events.jsonl" in ignore
    assert "sessions.jsonl" in ignore


def test_init_refuses_personal_dir(capsys, in_tmp, monkeypatch):
    monkeypatch.setenv("CAIRN_HOME", str(in_tmp / ".cairn"))
    code, _, err = run(capsys, "init")
    assert code == 1 and "scope personal" in err
    assert not (in_tmp / ".cairn").exists()


def test_init_refuses_store_inside_personal(capsys, in_tmp, monkeypatch):
    monkeypatch.setenv("CAIRN_HOME", str(in_tmp / "home"))
    (in_tmp / "home" / "sub").mkdir(parents=True)
    monkeypatch.chdir(in_tmp / "home" / "sub")
    code, _, err = run(capsys, "init")
    assert code == 1 and "scope personal" in err
    assert not (in_tmp / "home" / "sub" / ".cairn").exists()


def test_init_preserves_foreign_gitignore_lines(capsys, in_tmp):
    (in_tmp / ".cairn").mkdir()
    (in_tmp / ".cairn" / ".gitignore").write_text(
        "custom.txt\nevents.jsonl\n", encoding="utf-8"
    )
    assert run(capsys, "init", "--share")[0] == 0
    ignore = (in_tmp / ".cairn" / ".gitignore").read_text(encoding="utf-8")
    assert "custom.txt" in ignore and "events.jsonl" not in ignore
    assert run(capsys, "init")[0] == 0
    ignore = (in_tmp / ".cairn" / ".gitignore").read_text(encoding="utf-8")
    assert "custom.txt" in ignore and "events.jsonl" in ignore


def test_init_is_idempotent_and_share_can_be_reenabled(capsys, in_tmp):
    assert run(capsys, "init")[0] == 0
    assert run(capsys, "init", "--share")[0] == 0
    ignore = (in_tmp / ".cairn" / ".gitignore").read_text(encoding="utf-8")
    assert "events.jsonl" not in ignore


def test_init_refuses_nested_store(capsys, in_tmp, monkeypatch):
    assert run(capsys, "init")[0] == 0
    nested = in_tmp / "sub"
    nested.mkdir()
    monkeypatch.chdir(nested)
    code, _, err = run(capsys, "init")
    assert code == 1 and "ya existe un store" in err
    assert not (nested / ".cairn").exists()


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


def test_corrupt_db_tells_the_user_to_delete_it(capsys, in_tmp):
    (in_tmp / ".cairn").mkdir()
    (in_tmp / ".cairn" / "events.jsonl").touch()
    (in_tmp / ".cairn" / "cairn.db").write_bytes(b"no es una base de datos")
    code, _, err = run(capsys, "search", "x")
    assert code == 1 and "borra" in err


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


def test_save_regenerates_l0_and_render_matches(capsys, in_tmp):
    run(capsys, "init")
    run(capsys, "save", "--kind", "decision", "--title", "Usar FTS5", "--body", "bm25")
    text = (in_tmp / ".cairn" / "MEMORY.md").read_text(encoding="utf-8")
    assert "Usar FTS5" in text
    code, out, _ = run(capsys, "render")
    assert code == 0 and out == text


def test_check_lists_stale_after_anchor_change(capsys, in_tmp):
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
    assert "sin memorias stale" in run(capsys, "check")[1]
    (in_tmp / "a.py").write_text("v2\n", encoding="utf-8")
    code, out, _ = run(capsys, "check")
    assert code == 0 and "G" in out
    _, out, _ = run(capsys, "search", "x", "--json")
    assert json.loads(out)[0]["stale"] is True


def test_check_hashes_large_anchors(capsys, in_tmp, monkeypatch):
    import cairn_mem.anchor as anchor_module

    run(capsys, "init")
    target = in_tmp / "dump.csv"
    target.write_text("x" * 64, encoding="utf-8")
    run(
        capsys,
        "save",
        "--kind",
        "fact",
        "--title",
        "Dump",
        "--body",
        "x",
        "--anchor",
        "dump.csv",
    )
    monkeypatch.setattr(anchor_module, "MAX_HASH_BYTES", 1)
    assert "sin memorias stale" in run(capsys, "check")[1]


def test_personal_scope_is_separate(capsys, in_tmp):
    run(capsys, "init")
    _, out, _ = run(
        capsys,
        "save",
        "--kind",
        "convention",
        "--title",
        "Commits en LF",
        "--body",
        "todos los repos",
        "--personal",
        "--json",
    )
    mid = json.loads(out)["id"]
    assert (in_tmp / "home" / "events.jsonl").exists()
    assert "sin resultados" in run(capsys, "search", "commits")[1]
    assert "Commits en LF" in run(capsys, "search", "commits", "--personal")[1]
    _, out, _ = run(capsys, "get", mid, "--json")
    assert json.loads(out)["title"] == "Commits en LF"


def test_cairn_home_override(capsys, in_tmp, monkeypatch, tmp_path_factory):
    other = tmp_path_factory.mktemp("personal")
    monkeypatch.setenv("CAIRN_HOME", str(other))
    run(capsys, "init")
    run(
        capsys,
        "save",
        "--kind",
        "fact",
        "--title",
        "t",
        "--body",
        "b",
        "--personal",
    )
    assert (other / "events.jsonl").exists()
    assert "t" in run(capsys, "search", "t", "--personal")[1]


def test_session_commands(capsys, in_tmp):
    run(capsys, "init")
    (in_tmp / ".cairn" / ".gitignore").write_text("events.jsonl\n", encoding="utf-8")
    summary = "## Goal\nCerrar M6\n\n" + "detalle " * 500
    _, out, _ = run(capsys, "session", "save", "--summary", summary, "--json")
    sid = json.loads(out)["id"]
    assert "sessions.jsonl" in (in_tmp / ".cairn" / ".gitignore").read_text(
        encoding="utf-8"
    )
    code, out, _ = run(capsys, "session", "get", sid)
    assert code == 0 and "Cerrar M6" in out
    assert "Cerrar M6" in run(capsys, "session", "list")[1]
    assert "Cerrar M6" not in (in_tmp / ".cairn" / "events.jsonl").read_text(
        encoding="utf-8"
    )


def test_personal_dir_is_not_a_project_root(tmp_path, monkeypatch):
    from cairn_mem.paths import data_dir

    personal = tmp_path / ".cairn"
    personal.mkdir()
    (personal / "events.jsonl").touch()
    nested = tmp_path / "repo"
    nested.mkdir()
    monkeypatch.setenv("CAIRN_HOME", str(personal))
    monkeypatch.delenv("CAIRN_DIR", raising=False)
    monkeypatch.chdir(nested)
    with pytest.raises(FileNotFoundError):
        data_dir()


def test_personal_session_scope(capsys, in_tmp):
    run(capsys, "init")
    _, out, _ = run(
        capsys,
        "session",
        "save",
        "--summary",
        "resumen personal",
        "--personal",
        "--json",
    )
    sid = json.loads(out)["id"]
    assert (in_tmp / "home" / "sessions.jsonl").exists()
    assert "sin sesiones" in run(capsys, "session", "list")[1]
    assert "resumen personal" in run(capsys, "session", "list", "--personal")[1]
    assert "resumen personal" in run(capsys, "session", "get", sid, "--personal")[1]
