"""Precisión@3 del buscador sobre el golden set (sin LLM)."""

import json
from pathlib import Path

from cairn_mem.store import Store

GOLDEN = Path(__file__).resolve().parents[1] / "bench" / "golden.jsonl"
MIN_PRECISION = 0.8


def _load():
    entries = [
        json.loads(line)
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    corpus = [e for e in entries if e.get("op") == "save"]
    queries = [e for e in entries if "query" in e]
    return corpus, queries


def test_golden_set_shape():
    corpus, queries = _load()
    assert len(corpus) >= 15
    assert len(queries) >= 30


def test_precision_at_3(tmp_path):
    corpus, queries = _load()
    store = Store(str(tmp_path / ".cairn"))
    for memory in corpus:
        store.save(
            kind=memory["kind"],
            title=memory["title"],
            body=memory["body"],
            why=memory.get("why"),
        )
    hits = 0
    misses = []
    for query in queries:
        titles = [row["title"] for row in store.search(query["query"], limit=3)]
        if query["expect"] in titles:
            hits += 1
        else:
            misses.append((query["query"], query["expect"], titles))
    precision = hits / len(queries)
    assert precision >= MIN_PRECISION, (precision, misses)
