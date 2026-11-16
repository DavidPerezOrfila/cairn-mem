"""Guardas de los benches del backlog: relleno determinista y medición de anclas."""

import importlib.util
import json
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1] / "bench"
RETRIEVAL = BENCH / "bench_retrieval.py"
ANCHORS = BENCH / "bench_anchors.py"
DATASET = BENCH / "retrieval.jsonl"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _corpus_and_queries():
    entries = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    corpus = [entry for entry in entries if "title" in entry]
    queries = [entry for entry in entries if "query" in entry]
    return corpus, queries


def test_distractors_are_deterministic_and_do_not_collide():
    module = _module(RETRIEVAL, "bench_retrieval")
    corpus, queries = _corpus_and_queries()
    first = module.distractors(100)
    assert first == module.distractors(100)
    titles = {memory["title"] for memory in corpus}
    assert not titles & {memory["title"] for memory in first}
    expected = {title for query in queries for title in query["expect"]}
    assert not expected & {memory["title"] for memory in first}


def test_distractors_keep_the_dataset_metrics(tmp_path, capsys):
    """El relleno no se cuela como respuesta: las métricas no cambian."""
    module = _module(RETRIEVAL, "bench_retrieval")
    assert module.main(["--file", str(DATASET), "--json"]) == 0
    base = json.loads(capsys.readouterr().out)
    assert module.main(["--file", str(DATASET), "--distractors", "500", "--json"]) == 0
    scaled = json.loads(capsys.readouterr().out)
    assert scaled["memories"] == base["memories"] + 500
    assert scaled["summary"]["cairn"] == base["summary"]["cairn"]


def test_anchor_marginal_is_measured(tmp_path):
    module = _module(ANCHORS, "bench_anchors")
    root = tmp_path / ".cairn"
    root.mkdir()
    result = module.measure(root, count=200, anchors=5, anchor_kb=1, reps=3)
    assert result["memories"] == 200 and result["anchors"] == 5
    assert result["render_p50_ms"] >= 0 and result["save_p50_ms"] >= 0
    events = [
        json.loads(line)
        for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    anchored = [event for event in events if event.get("anchor_path")]
    assert len(anchored) == 5
    assert all(
        event["id"] in {f"{i:012x}" for i in range(195, 200)} for event in anchored
    )


def test_anchor_bench_main_runs_and_reports(capsys):
    module = _module(ANCHORS, "bench_anchors")
    assert module.main(["--count", "50", "--reps", "2"]) == 0
    output = capsys.readouterr().out
    assert "anchor_cache trigger" in output and "marginal" in output
