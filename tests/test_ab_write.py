"""S21: la parte determinista del A/B de escritura (sin LLM)."""

import importlib.util
import json
import re
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
    module = _module("ab_write")
    stop = tmp_path / "stop"
    module._prepare(stop, "stop", harness="claude-code")
    settings = json.loads(
        (stop / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
    script = stop / ".claude" / "hooks" / "cairn_stop.py"
    assert script.read_text(encoding="utf-8") == module.CC_HOOK
    assert script.resolve().as_posix() in command.replace("\\", "/").replace('"', "")
    # La línea base se fija al instalar: el equivalente al `before` del plugin.
    baseline = (stop / ".cairn-nudge" / "baseline").read_text(encoding="utf-8")
    assert baseline.strip() == "0"
    assert "stop_hook_active" in script.read_text(encoding="utf-8")


def test_cc_other_arms_do_not_install_the_hook(tmp_path):
    module = _module("ab_write")
    empty = tmp_path / "empty"
    module._prepare(empty, "empty", harness="claude-code")
    assert not (empty / ".claude" / "settings.json").exists()
    assert (empty / "AGENTS.md").read_text(encoding="utf-8") == module._snippet()


def test_cc_hook_text_is_the_measured_nudge():
    """El texto es el de la ronda 3 (S27): un solo mecanismo de empujón, un solo texto."""
    from cairn_mem.setup import HOOK_ASSET

    module = _module("ab_write")
    match = re.search(
        r"^const NUDGE = `(.*)`$", HOOK_ASSET.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert module.CC_NUDGE == match.group(1).replace("\\`", "`")


def test_cc_hook_nudges_once_and_only_without_a_save(tmp_path):
    module = _module("ab_write")
    project = tmp_path / "p"
    module._prepare(project, "stop", harness="claude-code")
    script = project / ".claude" / "hooks" / "cairn_stop.py"

    def hook(session_id, stop_hook_active=False):
        return subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(
                {
                    "session_id": session_id,
                    "cwd": str(project),
                    "stop_hook_active": stop_hook_active,
                }
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

    # Primera parada sin save: un empujón, y queda en el log del banco.
    first = hook("s1")
    assert first.returncode == 0
    decision = json.loads(first.stdout)
    assert decision["decision"] == "block" and decision["reason"] == module.CC_NUDGE
    assert module._nudges(project) == 1

    # Segunda parada de la misma sesión: nada (ni marcador nuevo ni segundo aviso).
    second = hook("s1")
    assert second.returncode == 0 and second.stdout.strip() == ""
    assert module._nudges(project) == 1

    # La sesión que ya guardó no se avisa; tampoco una continuación del propio hook.
    store = Store(str(project / ".cairn"))
    try:
        store.save(kind="gotcha", title="Epoch", body="time en epoch segundos")
    finally:
        store.close()
    saved = hook("s2")
    assert saved.returncode == 0 and saved.stdout.strip() == ""
    assert module._nudges(project) == 1
    continued = hook("s3", stop_hook_active=True)
    assert continued.returncode == 0 and continued.stdout.strip() == ""
    assert module._nudges(project) == 1
