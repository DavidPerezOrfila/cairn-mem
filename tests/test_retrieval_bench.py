"""Guardas del benchmark S6: dataset íntegro y métricas que no se pueden inflar."""

import importlib.util
import json
from pathlib import Path

from cairn_mem.store import KINDS

BENCH = Path(__file__).resolve().parents[1] / "bench" / "bench_retrieval.py"
DATASET = BENCH.parent / "retrieval.jsonl"
CATEGORIES = ("lexical", "paraphrase", "multi", "no_answer")


def _module():
    spec = importlib.util.spec_from_file_location("bench_retrieval", BENCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entries():
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_dataset_shape():
    entries = _entries()
    corpus = [entry for entry in entries if "title" in entry]
    queries = [entry for entry in entries if "query" in entry]
    titles = [memory["title"] for memory in corpus]
    assert len(corpus) >= 40
    assert len(queries) >= 30
    assert len(set(titles)) == len(titles)
    assert len({memory["id"] for memory in corpus}) == len(corpus)
    assert len({query["id"] for query in queries}) == len(queries)
    for memory in corpus:
        assert memory["kind"] in KINDS
        assert len(memory["body"]) <= 500
    for query in queries:
        assert query["category"] in CATEGORIES
        assert query["query"].strip()
        if query["category"] == "no_answer":
            assert query["expect"] == []
        else:
            assert query["expect"]
            assert set(query["expect"]) <= set(titles)


def test_score_counts_first_hit_and_multi_recall():
    module = _module()
    assert module.score(["a", "b"], ["b"]) == {"hit3": 1, "recall5": 1.0, "rr": 0.5}
    assert module.score(["a"], ["b"]) == {"hit3": 0, "recall5": 0.0, "rr": 0.0}
    assert module.score(["x", "y", "z", "a", "b"], ["a", "b"]) == {
        "hit3": 0,
        "recall5": 1.0,
        "rr": 0.25,
    }
    assert module.score(["a", "x", "b"], ["a", "b"])["recall5"] == 1.0


def test_summarize_abstention():
    module = _module()
    rows = [
        {"category": "no_answer", "abstained": True},
        {"category": "no_answer", "abstained": False},
        {"category": "lexical", "hit3": 1, "recall5": 1.0, "rr": 1.0},
    ]
    summary = module.summarize(rows)
    assert summary["no_answer"] == {"n": 2, "abstention": 0.5}
    assert summary["overall"]["hit3"] == 1.0


def test_grep_rank_ignores_stopwords():
    module = _module()
    corpus = [
        {"title": "Cache de plantillas Jinja", "body": "cache_size", "kind": "gotcha"},
        {"title": "Cache de pip en CI", "body": "pip", "kind": "decision"},
    ]
    assert module.grep_rank(corpus, "jinja", 5) == ["Cache de plantillas Jinja"]
    assert len(module.grep_rank(corpus, "cache", 5)) == 2
    assert module.grep_rank(corpus, "de la", 5) == []


def test_main_runs_end_to_end(capsys):
    module = _module()
    assert module.main(["--file", str(DATASET)]) == 0
    output = capsys.readouterr().out
    assert "overall" in output
    assert "abstained" in output
