"""Guardas de higiene de los benches: directorios limpios y código de salida del SLO."""

import importlib.util
import shutil
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


def _track_tempdirs(monkeypatch, tmp_path):
    """Manda los TemporaryDirectory del bench a tmp_path para poder comprobar el borrado."""
    created = []
    real = tempfile.TemporaryDirectory

    def factory(*args, **kwargs):
        kwargs["dir"] = tmp_path
        context = real(*args, **kwargs)
        created.append(context)
        return context

    monkeypatch.setattr(tempfile, "TemporaryDirectory", factory)
    return created


def test_store_close_releases_the_database(tmp_path):
    """Sin cerrar la conexión, Windows no deja borrar el `.cairn/`."""
    store = Store(str(tmp_path / ".cairn"))
    store.save(kind="fact", title="cierre", body="cuerpo")
    store.close()
    shutil.rmtree(tmp_path)


def test_cli_bench_exits_1_when_the_slo_fails(monkeypatch, tmp_path):
    module = _module("bench_cli")
    created = _track_tempdirs(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "SIZES", (10,))
    # Umbrales forzados: el veredicto no depende de la carga de la máquina.
    monkeypatch.setattr(module, "SEARCH_SLO_MS", 10**9)
    monkeypatch.setattr(module, "SAVE_SLO_MS", 10**9)
    assert module.main(["--reps", "1"]) == 0
    monkeypatch.setattr(module, "SEARCH_SLO_MS", 0)  # ningún p95 baja de 0 ms
    assert module.main(["--reps", "1"]) == 1
    assert module.main(["--reps", "1", "--json"]) == 1
    assert created and not list(tmp_path.iterdir())


def test_mcp_bench_exits_1_when_the_slo_fails(monkeypatch, tmp_path):
    module = _module("bench_mcp")
    created = _track_tempdirs(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "COUNT", 10)
    monkeypatch.setattr(module, "SLO_MS", 10**9)
    assert module.main(["--reps", "1", "--json"]) == 0
    monkeypatch.setattr(module, "SLO_MS", 0)
    assert module.main(["--reps", "1"]) == 1
    assert created and not list(tmp_path.iterdir())


def test_sync_bench_exits_1_when_the_slo_fails(monkeypatch, tmp_path):
    module = _module("bench_sync")
    created = _track_tempdirs(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "COUNT", 10)
    monkeypatch.setattr(module, "SLO_MS", 10**9)
    assert module.main(["--reps", "2", "--json"]) == 0
    monkeypatch.setattr(module, "SLO_MS", 0)
    assert module.main(["--reps", "2"]) == 1
    assert created and not list(tmp_path.iterdir())


def test_bench_closes_the_store_when_the_measurement_raises(monkeypatch, tmp_path):
    """Un error dentro del bucle no puede dejar el directorio sin borrar."""
    module = _module("bench_sync")
    created = _track_tempdirs(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "COUNT", 10)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(module.Store, "save", boom)
    with pytest.raises(RuntimeError):
        module.bench(2)
    assert created and not list(tmp_path.iterdir())


def test_anchor_bench_removes_its_temp_dir(monkeypatch, tmp_path):
    module = _module("bench_anchors")
    created = _track_tempdirs(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "SCENARIOS", ((2, 1),))
    assert module.main(["--count", "20", "--reps", "1"]) == 0
    assert created and not list(tmp_path.iterdir())


def test_retrieval_bench_removes_its_temp_dir(monkeypatch, tmp_path):
    module = _module("bench_retrieval")
    created = _track_tempdirs(monkeypatch, tmp_path)
    dataset = BENCH / "retrieval.jsonl"
    assert module.main(["--file", str(dataset), "--json"]) == 0
    assert created and not list(tmp_path.iterdir())
