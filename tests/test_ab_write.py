"""S21: la parte determinista del A/B de escritura (sin LLM)."""

import importlib.util
import json
import re
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from cairn_mem.store import Store

BENCH = Path(__file__).resolve().parents[1] / "bench"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_cc_hook(script, payload, cwd=None):
    return subprocess.run(
        [sys.executable, "-I", str(script)],
        input=json.dumps(payload),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def _write_cc_tool_transcript(path, name, tool_input, *, is_error=False):
    entries = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "tool-1", "name": name, "input": tool_input}
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "is_error": is_error,
                    }
                ]
            },
        },
    ]
    path.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )


def test_snippet_matches_what_setup_writes():
    """El A/B tiene que medir el bloque real: hasta 2026-11-20 cortaba por número de
    línea y metía dos frases de prosa y una valla en AGENTS.md."""
    from cairn_mem.setup import SNIPPET as PRODUCT

    assert _module("ab")._snippet().strip() == PRODUCT.strip()


def test_prepare_seeds_each_arm(tmp_path):
    module = _module("ab_write")
    plain = tmp_path / "plain"
    module._prepare(plain, "plain")
    assert (plain / "test_app.py").exists()
    assert not (plain / ".cairn").exists()

    empty = tmp_path / "empty"
    module._prepare(empty, "empty")
    text = (empty / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("## Project memory (cairn-mem)")
    assert "Before you reply" in text and "the user's reason" in text
    assert not (empty / ".cairn" / "events.jsonl").exists()

    poison = tmp_path / "poison"
    module._prepare(poison, "poison")
    store = Store(str(poison / ".cairn"))
    rows = store.search("formato del campo time")
    store.close()
    assert rows and rows[0]["topic_key"] == "health/time-format"


def test_stop_arm_installs_the_hook_and_the_others_do_not(tmp_path):
    """Criterio 5 del protocolo: el brazo `stop` es `imperative` + el hook, y solo él.
    Desde S28 instala el hook por la ruta real (`install_hook`), no una copia."""
    from cairn_mem.setup import HOOK_ASSET

    module = _module("ab_write")
    stop = tmp_path / "stop"
    module._prepare(stop, "stop")
    hook = stop / ".opencode" / "plugins" / "cairn-stop" / "index.ts"
    assert hook.read_bytes() == HOOK_ASSET.read_bytes()
    assert "session.execution.succeeded" in hook.read_text(encoding="utf-8")
    assert ".cairn-nudge.log" in hook.read_text(encoding="utf-8")
    assert (stop / "AGENTS.md").read_text(encoding="utf-8") == module._snippet()

    imperative = tmp_path / "imperative"
    module._prepare(imperative, "imperative")
    assert not (imperative / ".opencode").exists()


def test_nudges_come_from_the_hook_log(monkeypatch, tmp_path, capsys):
    module = _module("ab_write")
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "run"))

    def fake_run(directory, prompt, timeout=240):
        (directory / ".cairn-nudge.log").write_text("ses_1\nses_1\n", encoding="utf-8")
        return {"answer": "ok", "tokens": 5, "tools": 1, "exit": 0}

    monkeypatch.setattr(module, "_run", fake_run)
    assert module.main(["--arms", "stop", "--reps", "1", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert row["nudges"] == 2 and row["saved"] is False


def test_arms_run_interleaved_by_rep(monkeypatch, tmp_path, capsys):
    """Protocolo ronda 3: los dos brazos se intercalan para que la deriva del modelo no
    favorezca a uno."""
    module = _module("ab_write")
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "run"))
    monkeypatch.setattr(
        module,
        "_run",
        lambda directory, prompt, timeout=240: {
            "answer": "",
            "tokens": 1,
            "tools": 0,
            "exit": 0,
        },
    )
    assert module.main(["--arms", "imperative,stop", "--reps", "2", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["arm"] for row in rows] == ["imperative", "stop", "imperative", "stop"]


def test_only_new_saves_that_mention_the_gotcha_count(tmp_path):
    module = _module("ab_write")
    project = tmp_path / "p"
    module._prepare(project, "empty")
    events = project / ".cairn" / "events.jsonl"
    before = module._save_ids(events)
    store = Store(str(project / ".cairn"))
    store.save(kind="fact", title="Otra cosa", body="nada que ver")
    assert module._gotcha_saves(events, before) == []
    mid = store.save(
        kind="gotcha",
        title="Hora del servicio",
        body="clock.stamp() debe devolver UTC con tzinfo, no hora local naive",
    )
    store.close()
    found = module._gotcha_saves(events, before)
    assert [event["id"] for event in found] == [mid]
    # La semilla previa no cuenta como acierto de la corrida.
    assert module._gotcha_saves(events, set(before) | {mid}) == []


def test_wilson_interval_stays_inside_zero_one():
    module = _module("ab_write")
    low, high = module.wilson(0, 30)
    assert low == 0.0 and 0.1 < high < 0.12
    low, high = module.wilson(30, 30)
    assert high == 1.0 and 0.88 < low < 0.89
    assert module.wilson(0, 0) == (0.0, 1.0)


def test_main_counts_a_saved_gotcha_and_cleans_up(monkeypatch, tmp_path, capsys):
    module = _module("ab_write")
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "run"))

    def fake_run(directory, prompt, timeout=240):
        if not (directory / "AGENTS.md").exists():
            return {"answer": "nada", "tokens": 50, "tools": 3, "exit": 0}
        (directory / ".cairn").mkdir(parents=True, exist_ok=True)
        store = Store(str(directory / ".cairn"))
        store.save(kind="gotcha", title="UTC", body="usar datetime con timezone.utc")
        store.close()
        return {"answer": "hecho", "tokens": 100, "tools": 3, "exit": 0}

    monkeypatch.setattr(module, "_run", fake_run)
    assert module.main(["--arms", "empty,plain", "--reps", "1"]) == 0
    out = capsys.readouterr().out
    assert "empty" in out and "guardado 1/1" in out
    assert "plain" in out and "guardado 0/1" in out
    assert not list(tmp_path.iterdir())


def test_json_rows_carry_the_saved_text(monkeypatch, tmp_path, capsys):
    """Criterio 2 del protocolo: el veredicto se lee en las filas, no solo se cuenta."""
    module = _module("ab_write")
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "run"))

    def fake_run(directory, prompt, timeout=240):
        store = Store(str(directory / ".cairn"))
        store.save(kind="gotcha", title="UTC", body="epoch en segundos")
        store.close()
        return {"answer": "ok", "tokens": 5, "tools": 1, "exit": 0}

    monkeypatch.setattr(module, "_run", fake_run)
    assert module.main(["--arms", "empty", "--reps", "1", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)[0]
    assert row["saves"] == [
        {"kind": "gotcha", "title": "UTC", "body": "epoch en segundos", "why": None}
    ]


def test_rows_file_keeps_finished_sessions_when_a_later_run_fails(
    monkeypatch, tmp_path
):
    """Un corte de sesión conserva las filas ya terminadas y sigue limpiando el repo."""
    module = _module("ab_write")
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "run"))
    rows_file = tmp_path / "rows.jsonl"
    calls = 0
    finished_rows = []

    def fake_run(directory, prompt, timeout=240):
        nonlocal calls
        calls += 1
        if calls == 2:
            finished_rows.append(len(rows_file.read_text(encoding="utf-8").splitlines()))
            raise RuntimeError("session cutoff")
        store = Store(str(directory / ".cairn"))
        store.save(kind="gotcha", title="UTC", body="epoch en segundos")
        store.close()
        return {"answer": "ok", "tokens": 5, "tools": 1, "exit": 0}

    monkeypatch.setattr(module, "_run", fake_run)
    with pytest.raises(RuntimeError, match="session cutoff"):
        module.main(["--arms", "empty", "--reps", "2", "--rows-file", str(rows_file)])

    assert finished_rows == [1]
    rows = [
        json.loads(line) for line in rows_file.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["saved"] is True
    assert rows[0]["saves"][0]["title"] == "UTC"
    assert not (tmp_path / "run").exists()


def test_json_rows_carry_the_arm_and_the_result(monkeypatch, tmp_path, capsys):
    module = _module("ab_write")
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "run"))
    monkeypatch.setattr(
        module,
        "_run",
        lambda directory, prompt, timeout=240: {
            "answer": "ok",
            "tokens": 5,
            "tools": 1,
            "exit": 0,
        },
    )
    assert module.main(["--arms", "plain", "--reps", "2", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["arm"] for row in rows] == ["plain", "plain"]
    assert all(row["saved"] is False and row["exit"] == 0 for row in rows)


# Round 4 (S28 remainder): el brazo `stop` bajo el arnés claude-code.


def test_cc_stop_arm_writes_settings_hook_and_baseline(tmp_path):
    from cairn_mem.setup import CC_HOOK_ASSET

    module = _module("ab_write")
    stop = tmp_path / "stop"
    module._prepare(stop, "stop", harness="claude-code")
    script = stop / ".claude" / "hooks" / "cairn_stop.py"
    assert script.read_bytes() == CC_HOOK_ASSET.read_bytes()
    hook = {
        "type": "command",
        "command": sys.executable,
        "args": ["-I", script.resolve().as_posix()],
    }
    settings = {
        "hooks": {
            event: [{"hooks": [hook]}]
            for event in ("SessionStart", "Stop")
        }
    }
    assert (stop / ".claude" / "settings.json").read_bytes() == (
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    ).encode()
    # La línea base se fija al instalar: el equivalente al `before` del plugin.
    assert (stop / ".cairn-nudge" / "baseline").read_bytes() == b"0\n"
    assert (stop / ".gitignore").read_bytes() == b".cairn-nudge/\n.cairn-nudge.log\n"


def test_cc_hook_uses_the_measured_nudge():
    from cairn_mem.setup import CC_HOOK_ASSET, HOOK_ASSET

    asset = runpy.run_path(str(CC_HOOK_ASSET), run_name="cairn_cc_hook")
    match = re.search(
        r"^const NUDGE = `(.*)`$", HOOK_ASSET.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert match is not None
    assert asset["NUDGE"] == match.group(1).replace("\\`", "`")


def test_cc_other_arms_do_not_install_the_hook(tmp_path):
    module = _module("ab_write")
    empty = tmp_path / "empty"
    module._prepare(empty, "empty", harness="claude-code")
    assert not (empty / ".claude" / "settings.json").exists()
    assert (empty / "AGENTS.md").read_text(encoding="utf-8") == module._snippet()


def test_cc_hook_text_is_the_measured_nudge(tmp_path):
    from cairn_mem.setup import CC_HOOK_ASSET

    module = _module("ab_write")
    project = tmp_path / "p"
    module._prepare(project, "stop", harness="claude-code")
    installed = runpy.run_path(
        str(project / ".claude" / "hooks" / "cairn_stop.py"),
        run_name="installed_cairn_cc_hook",
    )
    asset = runpy.run_path(str(CC_HOOK_ASSET), run_name="cairn_cc_hook")
    assert installed["NUDGE"] == asset["NUDGE"]


def test_cc_hook_nudges_once_and_only_without_a_save(tmp_path):
    from cairn_mem.setup import CC_HOOK_ASSET

    module = _module("ab_write")
    project = tmp_path / "p"
    module._prepare(project, "stop", harness="claude-code")
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    asset = runpy.run_path(str(CC_HOOK_ASSET), run_name="cairn_cc_hook")

    def start(session_id):
        result = _run_cc_hook(
            script,
            {
                "session_id": session_id,
                "hook_event_name": "SessionStart",
                "cwd": str(project),
            },
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def hook(session_id, stop_hook_active=False):
        return _run_cc_hook(
            script,
            {
                "session_id": session_id,
                "hook_event_name": "Stop",
                "cwd": str(project),
                "stop_hook_active": stop_hook_active,
            },
        )

    # Primera parada sin save: un empujón, y queda en el log del banco.
    start("s1")
    first = hook("s1")
    assert first.returncode == 0
    decision = json.loads(first.stdout)
    assert decision["decision"] == "block" and decision["reason"] == asset["NUDGE"]
    assert module._nudges(project) == 1

    # Segunda parada de la misma sesión: nada (ni marcador nuevo ni segundo aviso).
    second = hook("s1")
    assert second.returncode == 0 and second.stdout.strip() == ""
    assert module._nudges(project) == 1

    # La sesión que ya guardó no se avisa; tampoco una continuación del propio hook.
    start("s2")
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="gotcha", title="Epoch", body="time en epoch segundos")
    finally:
        store.close()
    saved = hook("s2")
    assert saved.returncode == 0 and saved.stdout.strip() == ""
    assert module._nudges(project) == 1
    start("s3")
    continued = hook("s3", stop_hook_active=True)
    assert continued.returncode == 0 and continued.stdout.strip() == ""
    assert module._nudges(project) == 1


def test_cc_session_start_uses_a_per_session_save_baseline(tmp_path):
    from cairn_mem.setup import install_hook

    module = _module("ab_write")
    project = tmp_path / "p"
    module._prepare(project, "empty", harness="claude-code")
    install_hook("claude-code", project)
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    state_dir = project / ".cairn-nudge"

    def hook(session_id, event):
        result = _run_cc_hook(
            script,
            {
                "session_id": session_id,
                "hook_event_name": event,
                "cwd": str(project),
            },
        )
        assert result.returncode == 0, result.stderr
        return result

    assert hook("a", "SessionStart").stdout == ""
    assert (state_dir / "a.baseline").read_text(encoding="utf-8") == "0\n"
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="A saved", body="session a added this")
    finally:
        store.close()

    assert hook("b", "SessionStart").stdout == ""
    assert (state_dir / "b.baseline").read_text(encoding="utf-8") == "1\n"
    nudged = hook("b", "Stop")
    assert json.loads(nudged.stdout)["decision"] == "block"
    assert module._nudges(project) == 1
    assert hook("b", "Stop").stdout == ""

    # Una sesión que sí guardó no se avisa, ni aun si SessionStart se repite.
    assert hook("a", "SessionStart").stdout == ""
    assert hook("a", "Stop").stdout == ""
    assert module._nudges(project) == 1


def test_cc_transcript_attributes_saves_to_overlapping_sessions(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    script = project / ".claude" / "hooks" / "cairn_stop.py"

    def hook(session_id, event, transcript=None):
        payload = {
            "session_id": session_id,
            "hook_event_name": event,
            "cwd": str(project),
        }
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        result = _run_cc_hook(script, payload)
        assert result.returncode == 0, result.stderr
        return result

    transcript_a = tmp_path / "a.jsonl"
    transcript_b = tmp_path / "b.jsonl"
    transcript_a.write_text("", encoding="utf-8")
    transcript_b.write_text("", encoding="utf-8")
    assert hook("a", "SessionStart", transcript_a).stdout == ""
    assert hook("b", "SessionStart", transcript_b).stdout == ""
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="A saved", body="only session a saved")
    finally:
        store.close()

    _write_cc_tool_transcript(
        transcript_a, "mcp__cairn__save", {"body": "private transcript content"}
    )
    transcript_b = tmp_path / "b.jsonl"
    transcript_b.write_text(
        "not-json\n[]\nnull\n"
        '{"type":"assistant","message":{"content":[{"type":"tool_use",'
        '"id":"other","name":"mcp__other__save","input":{}}]}}\n'
        '{"type":"user","message":{"content":[{"type":"tool_result",'
        '"tool_use_id":"other","is_error":false}]}}\n'
        '{"type":"assistant","message":{"content":[{"type":"tool_use",'
        '"id":"echo","name":"Bash","input":{"command":"echo cairn save"}}]}}\n'
        '{"type":"user","message":{"content":[{"type":"tool_result",'
        '"tool_use_id":"echo","is_error":false}]}}\n',
        encoding="utf-8",
    )

    saved = hook("a", "Stop", transcript_a)
    assert saved.stdout == "" and saved.stderr == ""
    nudged = hook("b", "Stop", transcript_b)
    assert json.loads(nudged.stdout)["decision"] == "block"
    assert "private transcript content" not in nudged.stdout + nudged.stderr
    assert (project / ".cairn-nudge.log").read_text(encoding="utf-8") == "b\n"
    assert not (project / ".cairn-nudge" / "a.seen").exists()
    assert (project / ".cairn-nudge" / "b.seen").exists()


@pytest.mark.parametrize(
    ("name", "tool_input"),
    [
        ("mcp__cairn__save", {"body": "save"}),
        ("Bash", {"command": "cairn save --kind fact"}),
    ],
)
def test_cc_transcript_failed_save_result_still_nudges(tmp_path, name, tool_input):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "failed.jsonl"
    transcript.write_text("", encoding="utf-8")
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "failed",
        "hook_event_name": "Stop",
        "cwd": str(project),
        "transcript_path": str(transcript),
    }
    started = _run_cc_hook(script, {**payload, "hook_event_name": "SessionStart"})
    assert started.returncode == 0, started.stderr
    _write_cc_tool_transcript(transcript, name, tool_input, is_error=True)
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Other session", body="project save")
    finally:
        store.close()

    result = _run_cc_hook(script, payload)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "block"


@pytest.mark.parametrize(
    "command",
    [
        "cairn save --kind fact",
        "cairn-mem save --kind fact",
        "cairn.exe save --kind fact",
        "uv run cairn save --kind fact",
        "pipx run cairn-mem.exe save --kind fact",
        '"C:\\Program Files\\cairn.exe" save --kind fact',
        "echo ready && cairn save --kind fact",
        "echo ready &&\ncairn save --kind fact",
        "echo ready |\ncairn save --kind fact",
        "echo ready &\ncairn save --kind fact",
    ],
)
def test_cc_transcript_recognizes_successful_bash_saves(tmp_path, command):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "saved.jsonl"
    transcript.write_text("", encoding="utf-8")
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "bash-save",
        "hook_event_name": "Stop",
        "cwd": str(project),
        "transcript_path": str(transcript),
    }
    started = _run_cc_hook(script, {**payload, "hook_event_name": "SessionStart"})
    assert started.returncode == 0, started.stderr
    _write_cc_tool_transcript(transcript, "Bash", {"command": command})
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Saved", body="project save")
    finally:
        store.close()

    result = _run_cc_hook(script, payload)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not (project / ".cairn-nudge.log").exists()


@pytest.mark.parametrize(
    ("name", "tool_input"),
    [
        ("mcp__cairn__save", {"body": "save"}),
        ("Bash", {"command": "cairn save"}),
        ("mcp__cairn__save", {"body": "save", "scope": "personal"}),
        ("Bash", {"command": "cairn save --personal"}),
    ],
)
def test_cc_transcript_save_without_project_event_still_nudges(
    tmp_path, name, tool_input
):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "no-project-event.jsonl"
    transcript.write_text("", encoding="utf-8")
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "no-project-event",
        "hook_event_name": "Stop",
        "cwd": str(project),
        "transcript_path": str(transcript),
    }
    started = _run_cc_hook(script, {**payload, "hook_event_name": "SessionStart"})
    assert started.returncode == 0, started.stderr
    _write_cc_tool_transcript(transcript, name, tool_input)

    stopped = _run_cc_hook(script, payload)
    assert stopped.returncode == 0, stopped.stderr
    assert json.loads(stopped.stdout)["decision"] == "block"


@pytest.mark.parametrize(
    ("name", "tool_input"),
    [
        ("mcp__cairn__save", {"body": "save", "scope": "personal"}),
        ("Bash", {"command": "cairn save --personal"}),
    ],
)
def test_cc_transcript_personal_saves_do_not_satisfy_project_sessions(
    tmp_path, name, tool_input
):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "personal.jsonl"
    transcript.write_text("", encoding="utf-8")
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "personal-save",
        "hook_event_name": "Stop",
        "cwd": str(project),
        "transcript_path": str(transcript),
    }
    started = _run_cc_hook(script, {**payload, "hook_event_name": "SessionStart"})
    assert started.returncode == 0, started.stderr
    _write_cc_tool_transcript(transcript, name, tool_input)
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Other session", body="project save")
    finally:
        store.close()

    stopped = _run_cc_hook(script, payload)
    assert stopped.returncode == 0, stopped.stderr
    assert json.loads(stopped.stdout)["decision"] == "block"


def test_cc_transcript_ignores_pre_session_start_history(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "resumed.jsonl"
    _write_cc_tool_transcript(transcript, "mcp__cairn__save", {"body": "old save"})
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "resumed",
        "hook_event_name": "SessionStart",
        "cwd": str(project),
        "transcript_path": str(transcript),
        "source": "startup",
    }
    started = _run_cc_hook(script, payload)
    assert started.returncode == 0, started.stderr
    offset = project / ".cairn-nudge" / "resumed.offset"
    assert offset.read_text(encoding="utf-8") == f"{transcript.stat().st_size}\n"

    with transcript.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "old-save-2",
                                "name": "mcp__cairn__save",
                                "input": {},
                            }
                        ]
                    },
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "old-save-2",
                                "is_error": False,
                            }
                        ]
                    },
                }
            )
            + "\n"
        )
    resumed = _run_cc_hook(script, {**payload, "source": "resume"})
    assert resumed.returncode == 0, resumed.stderr
    assert offset.read_text(encoding="utf-8") == f"{transcript.stat().st_size}\n"
    assert (project / ".cairn-nudge" / "resumed.baseline").read_text() == "0\n"

    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Other session", body="project save")
    finally:
        store.close()
    with transcript.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {"type": "assistant", "message": {"content": [{"type": "text"}]}}
            )
            + "\n"
        )

    stopped = _run_cc_hook(script, {**payload, "hook_event_name": "Stop"})
    assert stopped.returncode == 0, stopped.stderr
    assert json.loads(stopped.stdout)["decision"] == "block"


def test_cc_compact_session_start_preserves_the_transcript_offset(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "compact.jsonl"
    transcript.write_text("", encoding="utf-8")
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "compact",
        "hook_event_name": "SessionStart",
        "cwd": str(project),
        "transcript_path": str(transcript),
        "source": "startup",
    }
    started = _run_cc_hook(script, payload)
    assert started.returncode == 0, started.stderr
    _write_cc_tool_transcript(transcript, "mcp__cairn__save", {"body": "before compact"})
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Saved", body="before compact")
    finally:
        store.close()

    compacted = _run_cc_hook(script, {**payload, "source": "compact"})
    assert compacted.returncode == 0, compacted.stderr
    offset = project / ".cairn-nudge" / "compact.offset"
    assert offset.read_text(encoding="utf-8") == "0\n"
    stopped = _run_cc_hook(script, {**payload, "hook_event_name": "Stop"})
    assert stopped.returncode == 0, stopped.stderr
    assert stopped.stdout == ""


def test_cc_transcript_without_session_offset_uses_baseline_fallback(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "underway.jsonl"
    _write_cc_tool_transcript(transcript, "mcp__cairn__save", {"body": "before install"})

    result = _run_cc_hook(
        project / ".claude" / "hooks" / "cairn_stop.py",
        {
            "session_id": "underway-transcript",
            "hook_event_name": "Stop",
            "cwd": str(project),
            "transcript_path": str(transcript),
        },
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "block"


def test_cc_truncated_transcript_keeps_the_baseline_fallback(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "truncated.jsonl"
    _write_cc_tool_transcript(transcript, "mcp__cairn__save", {"body": "old save"})
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "truncated",
        "hook_event_name": "SessionStart",
        "cwd": str(project),
        "transcript_path": str(transcript),
    }
    started = _run_cc_hook(script, payload)
    assert started.returncode == 0, started.stderr
    transcript.write_text("", encoding="utf-8")
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Other session", body="project save")
    finally:
        store.close()

    stopped = _run_cc_hook(script, {**payload, "hook_event_name": "Stop"})
    assert stopped.returncode == 0, stopped.stderr
    assert stopped.stdout == ""


def test_cc_resume_without_transcript_invalidates_the_old_offset(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "missing-on-resume.jsonl"
    transcript.write_text("", encoding="utf-8")
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "missing-on-resume",
        "hook_event_name": "SessionStart",
        "cwd": str(project),
        "transcript_path": str(transcript),
    }
    started = _run_cc_hook(script, payload)
    assert started.returncode == 0, started.stderr
    offset = project / ".cairn-nudge" / "missing-on-resume.offset"
    assert offset.exists()

    resumed = _run_cc_hook(script, {**payload, "transcript_path": None})
    assert resumed.returncode == 0, resumed.stderr
    assert not offset.exists()
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Other session", body="project save")
    finally:
        store.close()

    stopped = _run_cc_hook(script, {**payload, "hook_event_name": "Stop"})
    assert stopped.returncode == 0, stopped.stderr
    assert stopped.stdout == ""


def test_cc_home_relative_transcript_path_records_the_offset(tmp_path, monkeypatch):
    from cairn_mem.setup import install_hook

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    transcript = home / "relative.jsonl"
    transcript.write_text("", encoding="utf-8")
    project = tmp_path / "p"
    install_hook("claude-code", project)
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "home-relative",
        "hook_event_name": "SessionStart",
        "cwd": str(project),
        "transcript_path": "~/relative.jsonl",
    }
    started = _run_cc_hook(script, payload)
    assert started.returncode == 0, started.stderr
    offset = project / ".cairn-nudge" / "home-relative.offset"
    assert offset.read_text(encoding="utf-8") == "0\n"


def test_cc_unparseable_transcript_keeps_the_baseline_fallback(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "unparseable.jsonl"
    transcript.write_text("", encoding="utf-8")
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "unparseable-transcript",
        "hook_event_name": "Stop",
        "cwd": str(project),
        "transcript_path": str(transcript),
    }
    started = _run_cc_hook(script, {**payload, "hook_event_name": "SessionStart"})
    assert started.returncode == 0, started.stderr
    transcript.write_text("not-json\n[]\nnull\n", encoding="utf-8")
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Saved", body="baseline fallback")
    finally:
        store.close()

    result = _run_cc_hook(script, payload)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_cc_pending_save_result_still_nudges_once(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    transcript = tmp_path / "pending.jsonl"
    transcript.write_text("", encoding="utf-8")
    payload = {
        "session_id": "pending",
        "hook_event_name": "SessionStart",
        "cwd": str(project),
        "transcript_path": str(transcript),
    }
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    started = _run_cc_hook(script, payload)
    assert started.returncode == 0, started.stderr
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "pending-save",
                            "name": "mcp__cairn__save",
                            "input": {},
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Other session", body="project save")
    finally:
        store.close()

    first = _run_cc_hook(script, {**payload, "hook_event_name": "Stop"})
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["decision"] == "block"
    second = _run_cc_hook(script, {**payload, "stop_hook_active": True})
    assert second.returncode == 0, second.stderr
    assert second.stdout == ""
    assert (project / ".cairn-nudge.log").read_text(encoding="utf-8") == "pending\n"


def test_cc_unreadable_transcript_keeps_the_baseline_fallback(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    script = project / ".claude" / "hooks" / "cairn_stop.py"
    payload = {
        "session_id": "missing-transcript",
        "hook_event_name": "Stop",
        "cwd": str(project),
        "transcript_path": str(tmp_path / "missing.jsonl"),
    }
    started = _run_cc_hook(script, {**payload, "hook_event_name": "SessionStart"})
    assert started.returncode == 0, started.stderr
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Saved", body="baseline fallback")
    finally:
        store.close()

    result = _run_cc_hook(script, payload)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_cc_install_baseline_is_only_the_fallback_for_an_underway_session(tmp_path):
    from cairn_mem.setup import install_hook

    module = _module("ab_write")
    project = tmp_path / "p"
    module._prepare(project, "empty", harness="claude-code")
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="fact", title="Before install", body="already saved")
    finally:
        store.close()
    install_hook("claude-code", project)
    assert (project / ".cairn-nudge" / "baseline").read_text() == "1\n"

    result = _run_cc_hook(
        project / ".claude" / "hooks" / "cairn_stop.py",
        {
            "session_id": "underway",
            "hook_event_name": "Stop",
            "cwd": str(project),
        },
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "block"


def test_cc_hook_uses_the_installed_repo_not_the_incoming_cwd(tmp_path):
    from cairn_mem.cli import main

    project = tmp_path / "installed repo"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    assert main(["setup", "claude-code", "--dir", str(project)]) == 0

    result = _run_cc_hook(
        project / ".claude" / "hooks" / "cairn_stop.py",
        {
            "session_id": "root",
            "hook_event_name": "Stop",
            "cwd": str(nested),
        },
        cwd=outside,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "block"
    assert (project / ".cairn-nudge.log").read_text(encoding="utf-8") == "root\n"
    assert (project / ".cairn-nudge" / "root.seen").exists()
    assert not (nested / ".cairn-nudge").exists()
    assert not (outside / ".cairn-nudge").exists()


@pytest.mark.parametrize("payload", [[], None, "text", 7, True])
def test_cc_hook_ignores_non_object_payloads(tmp_path, payload):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    result = _run_cc_hook(
        project / ".claude" / "hooks" / "cairn_stop.py", payload
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert [path.name for path in (project / ".cairn-nudge").iterdir()] == ["baseline"]
    assert not (project / ".cairn-nudge.log").exists()


@pytest.mark.parametrize(
    "session_id",
    ["../escape", "..\\escape", "line\nbreak", "", "x" * 201, None, 7, "absolute"],
)
def test_cc_hook_rejects_invalid_session_ids_without_writes(tmp_path, session_id):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    outside = tmp_path / "outside"
    outside.mkdir()
    if session_id == "absolute":
        session_id = str(outside / "absolute")
    script = project / ".claude" / "hooks" / "cairn_stop.py"

    for event in ("SessionStart", "Stop"):
        result = _run_cc_hook(
            script,
            {
                "session_id": session_id,
                "hook_event_name": event,
                "cwd": str(outside),
            },
            cwd=outside,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    assert list(outside.iterdir()) == []
    assert [path.name for path in (project / ".cairn-nudge").iterdir()] == ["baseline"]
    assert not (project / ".cairn-nudge.log").exists()


def test_cc_hook_skips_non_object_jsonl_values(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    events = project / ".cairn" / "events.jsonl"
    events.parent.mkdir()
    events.write_text(
        '[]\nnull\n"save"\n1\n{"op": "archive"}\nnot-json\n', encoding="utf-8"
    )

    result = _run_cc_hook(
        project / ".claude" / "hooks" / "cairn_stop.py",
        {
            "session_id": "jsonl",
            "hook_event_name": "Stop",
            "cwd": str(project),
        },
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "block"


def test_cc_hook_rejects_a_symlink_log_without_writing_outside(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    outside = tmp_path / "outside.log"
    outside.write_text("outside\n", encoding="utf-8")
    try:
        (project / ".cairn-nudge.log").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this host")

    result = _run_cc_hook(
        project / ".claude" / "hooks" / "cairn_stop.py",
        {
            "session_id": "symlink",
            "hook_event_name": "Stop",
            "cwd": str(project),
        },
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "block"
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_cc_hook_logging_failure_does_not_prevent_the_nudge(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    (project / ".cairn-nudge.log").mkdir()

    result = _run_cc_hook(
        project / ".claude" / "hooks" / "cairn_stop.py",
        {
            "session_id": "log-failure",
            "hook_event_name": "Stop",
            "cwd": str(project),
        },
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "block"
    assert (project / ".cairn-nudge.log").is_dir()


def test_cc_hook_isolated_mode_blocks_sibling_module_shadowing(tmp_path):
    from cairn_mem.setup import install_hook

    project = tmp_path / "p"
    install_hook("claude-code", project)
    (project / ".claude" / "hooks" / "json.py").write_text(
        'raise RuntimeError("shadowed json")\n', encoding="utf-8"
    )

    result = _run_cc_hook(
        project / ".claude" / "hooks" / "cairn_stop.py",
        {
            "session_id": "isolated",
            "hook_event_name": "SessionStart",
            "cwd": str(project),
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (project / ".cairn-nudge" / "isolated.baseline").read_text() == "0\n"
