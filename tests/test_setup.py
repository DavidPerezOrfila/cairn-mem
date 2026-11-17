"""Tests de `cairn setup` (S16): config MCP y snippet por harness."""

import json
import re
from pathlib import Path

import pytest

from cairn_mem.cli import main
from cairn_mem.setup import BEGIN, END, HARNESSES, SNIPPET


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


def test_claude_code_writes_config_and_instructions(capsys, in_tmp):
    code, out, _ = run(capsys, "setup", "claude-code")
    assert code == 0
    config = json.loads((in_tmp / ".mcp.json").read_text(encoding="utf-8"))
    assert config["mcpServers"]["cairn"] == {"command": "cairn", "args": ["mcp"]}
    rules = (in_tmp / "CLAUDE.md").read_text(encoding="utf-8")
    assert BEGIN in rules and END in rules and SNIPPET.strip() in rules
    assert ".mcp.json" in out and "CLAUDE.md" in out


def test_opencode_writes_schema_and_local_server(capsys, in_tmp):
    code, _, _ = run(capsys, "setup", "opencode")
    assert code == 0
    config = json.loads((in_tmp / "opencode.json").read_text(encoding="utf-8"))
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["mcp"]["servers"]["cairn"] == {
        "type": "local",
        "command": ["cairn", "mcp"],
    }
    assert BEGIN in (in_tmp / "AGENTS.md").read_text(encoding="utf-8")


def test_existing_config_keeps_other_keys(capsys, in_tmp):
    (in_tmp / "opencode.json").write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "model": "x/y",
                "mcp": {"servers": {"other": {"type": "local", "command": ["npx"]}}},
            }
        ),
        encoding="utf-8",
    )
    assert run(capsys, "setup", "opencode")[0] == 0
    config = json.loads((in_tmp / "opencode.json").read_text(encoding="utf-8"))
    assert config["model"] == "x/y"
    assert config["mcp"]["servers"]["other"]["command"] == ["npx"]
    assert config["mcp"]["servers"]["cairn"]["command"] == ["cairn", "mcp"]


def test_second_run_changes_nothing(capsys, in_tmp):
    assert run(capsys, "setup", "claude-code")[0] == 0
    config = (in_tmp / ".mcp.json").read_bytes()
    rules = (in_tmp / "CLAUDE.md").read_bytes()
    code, out, _ = run(capsys, "setup", "claude-code")
    assert code == 0
    assert (in_tmp / ".mcp.json").read_bytes() == config
    assert (in_tmp / "CLAUDE.md").read_bytes() == rules
    assert rules.count(BEGIN.encode()) == 1
    assert "ya estaba" in out


def test_snippet_is_refreshed_between_markers(capsys, in_tmp):
    (in_tmp / "AGENTS.md").write_text(
        f"# mío\n\n{BEGIN}\nviejo\n{END}\n\ntexto del usuario\n", encoding="utf-8"
    )
    assert run(capsys, "setup", "opencode")[0] == 0
    rules = (in_tmp / "AGENTS.md").read_text(encoding="utf-8")
    assert "viejo" not in rules
    assert SNIPPET.strip() in rules
    assert rules.startswith("# mío") and rules.endswith("texto del usuario\n")


def test_commented_config_is_refused(capsys, in_tmp):
    original = '{\n  // comentario\n  "model": "x/y"\n}\n'
    (in_tmp / "opencode.json").write_text(original, encoding="utf-8")
    code, _, err = run(capsys, "setup", "opencode")
    assert code == 1
    assert "a mano" in err and "cairn" in err
    assert (in_tmp / "opencode.json").read_text(encoding="utf-8") == original


def test_config_that_is_not_an_object_is_refused(capsys, in_tmp):
    (in_tmp / "opencode.json").write_text("[]", encoding="utf-8")
    code, _, err = run(capsys, "setup", "opencode")
    assert code == 1
    assert "objeto JSON" in err
    assert (in_tmp / "opencode.json").read_text(encoding="utf-8") == "[]"


def test_crlf_instructions_file_is_normalized(capsys, in_tmp):
    (in_tmp / "CLAUDE.md").write_bytes(b"# previo\r\n\r\ntexto\r\n")
    assert run(capsys, "setup", "claude-code")[0] == 0
    raw = (in_tmp / "CLAUDE.md").read_bytes()
    assert b"\r" not in raw
    assert SNIPPET.strip().encode() in raw


def test_dir_option_writes_elsewhere(capsys, in_tmp):
    target = in_tmp / "repo"
    assert run(capsys, "setup", "claude-code", "--dir", str(target))[0] == 0
    assert (target / ".mcp.json").exists()
    assert not (in_tmp / ".mcp.json").exists()


def test_unknown_harness_is_rejected(capsys, in_tmp):
    with pytest.raises(SystemExit) as error:
        run(capsys, "setup", "emacs")
    assert error.value.code == 2
    assert set(HARNESSES) == {"claude-code", "opencode"}


def test_snippet_matches_the_documentation(in_tmp):
    doc = (Path(__file__).parents[1] / "docs" / "AGENT_SNIPPET.md").read_text(
        encoding="utf-8"
    )
    fenced = re.search(r"```markdown\n(.*?)```", doc, re.DOTALL)
    assert fenced is not None
    assert fenced.group(1).strip() == SNIPPET.strip()
