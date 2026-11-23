"""El gate del eval MCP: daño al store real detectado y reparado (2026-11-23).

El agente evaluado no está sandboxeado: `c13` archivó 29 memorias reales y
`c14` borró `events.jsonl`. El gate no lo contiene, pero detecta el daño tras
cada caso y lo restaura del snapshot."""

import importlib.util
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1] / "bench"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_untouched_store_reports_no_damage(tmp_path):
    module = _module("eval_mcp_tools")
    (tmp_path / "events.jsonl").write_bytes(b'{"op":"save","id":"aa"}\n')
    (tmp_path / "sessions.jsonl").write_bytes(b'{"id":"bb"}\n')
    snapshot = module._snapshot_guard(tmp_path)
    assert set(snapshot) == {"events.jsonl", "sessions.jsonl"}
    assert module._check_guard(tmp_path, snapshot) == []


def test_destroyed_file_is_restored(tmp_path):
    module = _module("eval_mcp_tools")
    (tmp_path / "events.jsonl").write_bytes(b"one\n")
    snapshot = module._snapshot_guard(tmp_path)
    (tmp_path / "events.jsonl").unlink()
    assert module._check_guard(tmp_path, snapshot) == ["events.jsonl"]
    assert (tmp_path / "events.jsonl").read_bytes() == b"one\n"


def test_mutated_file_is_restored_and_damage_is_attributed(tmp_path):
    module = _module("eval_mcp_tools")
    (tmp_path / "events.jsonl").write_bytes(b"one\n")
    snapshot = module._snapshot_guard(tmp_path)
    (tmp_path / "events.jsonl").write_bytes(b"one\n" + b'{"op":"archive"}\n')
    assert module._check_guard(tmp_path, snapshot) == ["events.jsonl"]
    assert (tmp_path / "events.jsonl").read_bytes() == b"one\n"
    # Un segundo check sin daño nuevo no repite la reparación.
    assert module._check_guard(tmp_path, snapshot) == []


def test_file_created_by_the_agent_is_removed(tmp_path):
    module = _module("eval_mcp_tools")
    snapshot = module._snapshot_guard(tmp_path)
    (tmp_path / "sessions.jsonl").write_bytes(b'{"id":"cc"}\n')
    assert module._check_guard(tmp_path, snapshot) == ["sessions.jsonl"]
    assert not (tmp_path / "sessions.jsonl").exists()
