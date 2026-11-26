"""Tests de `cairn setup` (S16): config MCP y snippet por harness."""

import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

from cairn_mem.cli import main
from cairn_mem.setup import BEGIN, END, HARNESSES, HOOK_ASSET, SNIPPET


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


def test_config_with_a_utf8_bom_is_read(capsys, in_tmp):
    """Windows puede escribir el config con BOM: no es "JSON no estricto"."""
    (in_tmp / "opencode.json").write_bytes(b'\xef\xbb\xbf{"model": "x/y"}\n')
    assert run(capsys, "setup", "opencode")[0] == 0
    config = json.loads((in_tmp / "opencode.json").read_text(encoding="utf-8"))
    assert config["model"] == "x/y"
    assert config["mcp"]["servers"]["cairn"]["command"] == ["cairn", "mcp"]


def test_second_run_changes_nothing(capsys, in_tmp):
    assert run(capsys, "setup", "claude-code")[0] == 0
    paths = [
        in_tmp / ".mcp.json",
        in_tmp / "CLAUDE.md",
        in_tmp / HARNESSES["claude-code"]["hook"],
        in_tmp / ".claude" / "settings.json",
        in_tmp / ".cairn-nudge" / "baseline",
        in_tmp / ".gitignore",
    ]
    before = {path: path.read_bytes() for path in paths}
    code, out, _ = run(capsys, "setup", "claude-code")
    assert code == 0
    assert {path: path.read_bytes() for path in paths} == before
    assert before[in_tmp / "CLAUDE.md"].count(BEGIN.encode()) == 1
    settings = json.loads(before[in_tmp / ".claude" / "settings.json"])
    script = in_tmp / HARNESSES["claude-code"]["hook"]
    hook = {
        "type": "command",
        "command": sys.executable,
        "args": ["-I", script.resolve().as_posix()],
    }
    for event in ("SessionStart", "Stop"):
        commands = [
            hook
            for group in settings["hooks"][event]
            for hook in group["hooks"]
        ]
        assert commands.count(hook) == 1
    assert "already there" in out


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
    assert "by hand" in err and "cairn" in err
    assert (in_tmp / "opencode.json").read_text(encoding="utf-8") == original


def test_config_that_is_not_an_object_is_refused(capsys, in_tmp):
    (in_tmp / "opencode.json").write_text("[]", encoding="utf-8")
    code, _, err = run(capsys, "setup", "opencode")
    assert code == 1
    assert "JSON object" in err
    assert (in_tmp / "opencode.json").read_text(encoding="utf-8") == "[]"


def test_crlf_instructions_file_is_normalized(capsys, in_tmp):
    (in_tmp / "CLAUDE.md").write_bytes(b"# previo\r\n\r\ntexto\r\n")
    assert run(capsys, "setup", "claude-code")[0] == 0
    raw = (in_tmp / "CLAUDE.md").read_bytes()
    assert b"\r" not in raw
    assert SNIPPET.strip().encode() in raw


def test_claude_md_that_imports_agents_md_gets_no_block(capsys, in_tmp):
    original = "# mío\n\n@AGENTS.md\n"
    (in_tmp / "CLAUDE.md").write_text(original, encoding="utf-8")
    code, out, _ = run(capsys, "setup", "claude-code")
    assert code == 0
    assert (in_tmp / "CLAUDE.md").read_text(encoding="utf-8") == original
    assert "@AGENTS.md" in out


def test_import_removes_a_block_left_by_an_older_setup(capsys, in_tmp):
    (in_tmp / "CLAUDE.md").write_text(
        f"# mío\n\n@AGENTS.md\n\n{BEGIN}\nviejo\n{END}\n", encoding="utf-8"
    )
    assert run(capsys, "setup", "claude-code")[0] == 0
    rules = (in_tmp / "CLAUDE.md").read_text(encoding="utf-8")
    assert rules == "# mío\n\n@AGENTS.md\n"
    assert run(capsys, "setup", "claude-code")[0] == 0
    assert (in_tmp / "CLAUDE.md").read_text(encoding="utf-8") == rules


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


def test_opencode_installs_the_measured_hook(capsys, in_tmp):
    """S28: el hook que se instala es byte a byte el que midió S27."""
    assert run(capsys, "setup", "opencode")[0] == 0
    hook = in_tmp / HARNESSES["opencode"]["hook"]
    assert hook.read_text(encoding="utf-8") == HOOK_ASSET.read_text(encoding="utf-8")
    assert "session.execution.succeeded" in hook.read_text(encoding="utf-8")


def test_hook_install_is_idempotent(capsys, in_tmp):
    assert run(capsys, "setup", "opencode")[0] == 0
    hook = in_tmp / HARNESSES["opencode"]["hook"]
    before = hook.read_bytes()
    code, out, _ = run(capsys, "setup", "opencode")
    assert code == 0 and hook.read_bytes() == before
    assert f"hook: {hook}" in out and "already there" in out


def test_claude_code_installs_the_measured_hook(capsys, in_tmp):
    from cairn_mem.setup import CC_HOOK_ASSET

    code, out, _ = run(capsys, "setup", "claude-code")
    assert code == 0
    script = in_tmp / HARNESSES["claude-code"]["hook"]
    assert script.read_bytes() == CC_HOOK_ASSET.read_bytes()
    settings = json.loads(
        (in_tmp / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    hook = {
        "type": "command",
        "command": sys.executable,
        "args": ["-I", script.resolve().as_posix()],
    }
    for event in ("SessionStart", "Stop"):
        assert settings["hooks"][event] == [{"hooks": [hook]}]
    baseline = in_tmp / ".cairn-nudge" / "baseline"
    assert baseline.read_text(encoding="utf-8") == "0\n"
    ignores = (in_tmp / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".cairn-nudge/" in ignores and ".cairn-nudge.log" in ignores
    assert f"hook: {script}" in out


def test_claude_code_preserves_settings_and_existing_session_hooks(capsys, in_tmp):
    existing = {
        "type": "command",
        "command": "echo existing",
        "timeout": 10,
    }
    original = {
        "permissions": {"allow": ["Bash"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [existing]}],
            "SessionStart": [{"matcher": "startup", "hooks": [existing]}],
            "Stop": [
                {"matcher": "", "hooks": [existing]},
                {"matcher": "Bash"},
            ],
        },
    }
    settings_path = in_tmp / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps(original), encoding="utf-8")
    assert run(capsys, "setup", "claude-code")[0] == 0
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["permissions"] == original["permissions"]
    assert settings["hooks"]["PreToolUse"] == original["hooks"]["PreToolUse"]
    assert settings["hooks"]["SessionStart"][0] == original["hooks"]["SessionStart"][0]
    assert settings["hooks"]["Stop"][0] == original["hooks"]["Stop"][0]
    assert settings["hooks"]["Stop"][1] == original["hooks"]["Stop"][1]
    assert len(settings["hooks"]["SessionStart"]) == 2
    assert len(settings["hooks"]["Stop"]) == 3
    script = in_tmp / HARNESSES["claude-code"]["hook"]
    hook = {
        "type": "command",
        "command": sys.executable,
        "args": ["-I", script.resolve().as_posix()],
    }
    assert settings["hooks"]["SessionStart"][1] == {"hooks": [hook]}
    assert settings["hooks"]["Stop"][2] == {"hooks": [hook]}


def test_claude_code_never_resets_an_existing_baseline(capsys, in_tmp):
    from cairn_mem.store import Store

    store = Store(str(in_tmp / ".cairn"))
    try:
        store.save(kind="fact", title="First", body="first save")
        store.save(kind="fact", title="Second", body="second save")
    finally:
        store.close()
    assert run(capsys, "setup", "claude-code")[0] == 0
    baseline = in_tmp / ".cairn-nudge" / "baseline"
    assert baseline.read_bytes() == b"2\n"

    store = Store(str(in_tmp / ".cairn"))
    try:
        store.save(kind="fact", title="Third", body="third save")
    finally:
        store.close()
    assert run(capsys, "setup", "claude-code")[0] == 0
    assert baseline.read_bytes() == b"2\n"


@pytest.mark.parametrize(
    "original",
    [
        b"{not json}\n",
        b"[]\n",
        b'{"hooks": []}\n',
        b'{"hooks": {"Stop": {}}}\n',
        b'{"hooks": {"SessionStart": {}}}\n',
        b'{"hooks": {"SessionStart": [1]}}\n',
        b'{"hooks": {"SessionStart": [{"hooks": {}}]}}\n',
        b'{"hooks": {"SessionStart": [{"hooks": [1]}]}}\n',
    ],
)
def test_invalid_claude_settings_are_refused_without_writes(capsys, in_tmp, original):
    settings_path = in_tmp / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_bytes(original)
    code, _, err = run(capsys, "setup", "claude-code")
    assert code == 1
    assert settings_path.read_bytes() == original
    assert "cairn:" in err
    assert not (in_tmp / ".claude" / "hooks").exists()
    assert not (in_tmp / ".cairn-nudge").exists()
    assert not (in_tmp / ".gitignore").exists()
    assert not (in_tmp / ".mcp.json").exists()
    assert not (in_tmp / "CLAUDE.md").exists()


def test_claude_code_preserves_foreign_gitignore_entries(capsys, in_tmp):
    original = "# user rules\nnode_modules/\n"
    (in_tmp / ".gitignore").write_text(original, encoding="utf-8")
    assert run(capsys, "setup", "claude-code")[0] == 0
    assert run(capsys, "setup", "claude-code")[0] == 0
    text = (in_tmp / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith(original)
    assert text.count(".cairn-nudge/") == 1
    assert text.count(".cairn-nudge.log") == 1
    assert "\r" not in text


def test_claude_code_hook_uses_exec_form_for_shell_metacharacters(capsys, in_tmp):
    target = in_tmp / "repo $(touch injected)"
    assert run(capsys, "setup", "claude-code", "--dir", str(target))[0] == 0
    settings = json.loads(
        (target / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    script = target / HARNESSES["claude-code"]["hook"]
    hook = {
        "type": "command",
        "command": sys.executable,
        "args": ["-I", script.resolve().as_posix()],
    }
    for event in ("SessionStart", "Stop"):
        assert settings["hooks"][event] == [{"hooks": [hook]}]
    assert not (target / "injected").exists()


@pytest.mark.parametrize("harness", ["claude-code", "opencode"])
def test_existing_unrelated_hook_is_not_overwritten(capsys, in_tmp, harness):
    script = in_tmp / HARNESSES[harness]["hook"]
    script.parent.mkdir(parents=True)
    original = b"print('user hook')\n"
    script.write_bytes(original)
    code, _, err = run(capsys, "setup", harness)
    assert code == 1
    assert script.read_bytes() == original
    assert "cairn:" in err
    assert not (in_tmp / ".mcp.json").exists()
    assert not (in_tmp / "opencode.json").exists()
    assert not (in_tmp / "CLAUDE.md").exists()
    assert not (in_tmp / "AGENTS.md").exists()


def test_unreadable_events_abort_before_any_setup_write(capsys, in_tmp, monkeypatch):
    def unreadable(_path):
        raise PermissionError("events unavailable")

    monkeypatch.setattr("cairn_mem.setup._save_count", unreadable)
    code, _, err = run(capsys, "setup", "claude-code")
    assert code == 1
    assert "events unavailable" in err
    assert not (in_tmp / ".mcp.json").exists()
    assert not (in_tmp / "CLAUDE.md").exists()
    assert not (in_tmp / ".claude").exists()
    assert not (in_tmp / ".cairn-nudge").exists()
    assert not (in_tmp / ".gitignore").exists()


@pytest.mark.parametrize(
    "relative",
    [
        ".mcp.json",
        "CLAUDE.md",
        ".claude",
        ".claude/settings.json",
        ".claude/hooks/cairn_stop.py",
        ".cairn-nudge",
        ".cairn-nudge/baseline",
        ".cairn-nudge.log",
        ".gitignore",
    ],
)
def test_setup_refuses_symlink_destinations(
    capsys, in_tmp, tmp_path_factory, relative
):
    destination = in_tmp / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path_factory.mktemp("outside")
    is_directory = relative in {".claude", ".cairn-nudge"}
    target = outside if is_directory else outside / "target"
    if not is_directory:
        target.write_text("outside\n", encoding="utf-8")
    try:
        destination.symlink_to(target, target_is_directory=is_directory)
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    code, _, _ = run(capsys, "setup", "claude-code")
    assert code == 1
    assert not (in_tmp / ".mcp.json").exists() or relative == ".mcp.json"
    assert not (in_tmp / "CLAUDE.md").exists() or relative == "CLAUDE.md"
    if is_directory:
        assert not any(outside.iterdir())
    else:
        assert target.read_text(encoding="utf-8") == "outside\n"


def test_settings_replacement_is_atomic(in_tmp, monkeypatch):
    from cairn_mem.setup import CC_HOOK_ASSET, install_hook

    script = in_tmp / HARNESSES["claude-code"]["hook"]
    script.parent.mkdir(parents=True)
    script.write_bytes(CC_HOOK_ASSET.read_bytes())
    settings_path = in_tmp / ".claude" / "settings.json"
    original = b'{"permissions": {"allow": ["Bash"]}}\n'
    settings_path.write_bytes(original)

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr("cairn_mem.paths.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        install_hook("claude-code", in_tmp)
    assert settings_path.read_bytes() == original
    assert {path for path in (in_tmp / ".claude").rglob("*") if path.is_file()} == {
        script,
        settings_path,
    }


def test_gitignore_replacement_is_atomic(in_tmp, monkeypatch):
    from cairn_mem.paths import ignore_nudge

    path = in_tmp / ".gitignore"
    original = b"node_modules/\n"
    path.write_bytes(original)

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr("cairn_mem.paths.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        ignore_nudge(in_tmp)
    assert path.read_bytes() == original
    assert list(in_tmp.iterdir()) == [path]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_atomic_replacement_preserves_existing_mode_bits(in_tmp):
    from cairn_mem.paths import write_if_changed

    path = in_tmp / "settings.json"
    path.write_bytes(b"old\n")
    path.chmod(0o640)

    assert write_if_changed(path, b"new\n") is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
