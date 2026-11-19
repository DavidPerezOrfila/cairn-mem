"""S21: `CAIRN_LANG` — inglés por defecto y español opt-in."""

import json

import pytest

from cairn_mem.cli import main
from cairn_mem.i18n import language, t


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAIRN_DIR", raising=False)
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CAIRN_LANG", raising=False)
    return tmp_path


def run(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_language_defaults_to_english(monkeypatch):
    monkeypatch.delenv("CAIRN_LANG", raising=False)
    assert language() == "en"
    assert t("english", "español") == "english"


@pytest.mark.parametrize("value", ["es", "ES", " es ", "es-ES"])
def test_language_accepts_spanish_variants(monkeypatch, value):
    monkeypatch.setenv("CAIRN_LANG", value)
    assert t("english", "español") == "español"


@pytest.mark.parametrize("value", ["en", "fr", "de-DE", "klingon"])
def test_any_other_value_stays_english(monkeypatch, value):
    monkeypatch.setenv("CAIRN_LANG", value)
    assert t("english", "español") == "english"


def test_cli_messages_follow_the_language(capsys, monkeypatch):
    assert run(capsys, "init")[1].startswith("cairn initialized at")
    assert run(capsys, "search", "x")[1] == "no results\n"

    monkeypatch.setenv("CAIRN_LANG", "es")
    assert run(capsys, "search", "x")[1] == "sin resultados\n"
    code, _, err = run(capsys, "get", "000000000000")
    assert code == 1 and "no existe la memoria" in err


def test_doctor_details_follow_the_language(capsys, monkeypatch):
    run(capsys, "init")
    assert " characters" in run(capsys, "doctor")[1]
    monkeypatch.setenv("CAIRN_LANG", "es")
    out = run(capsys, "doctor")[1]
    assert " caracteres" in out and " characters" not in out


def test_setup_messages_follow_the_language(capsys, monkeypatch):
    assert "restart OpenCode" in run(capsys, "setup", "opencode")[1]
    monkeypatch.setenv("CAIRN_LANG", "es")
    assert run(capsys, "setup", "opencode")[1].endswith(
        "reinicia OpenCode en este repo\n"
    )


def test_json_output_is_not_translated(capsys, monkeypatch):
    monkeypatch.setenv("CAIRN_LANG", "es")
    run(capsys, "init")
    run(capsys, "save", "--kind", "fact", "--title", "t", "--body", "b")
    code, out, _ = run(capsys, "search", "t", "--json")
    assert code == 0
    assert json.loads(out)[0]["title"] == "t"
