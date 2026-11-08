"""S6: honest retrieval benchmark. Measures the current search, no ranking changes.

Metrics: Hit@3, Recall@5 and MRR over answerable queries, plus how often the
system abstains when nothing is stored for the query. Each metric is compared
against a literal grep baseline (term count over title, body and why).

Usage: python bench/bench_retrieval.py [--file bench/retrieval.jsonl] [--json]
"""

import argparse
import json
import re
import tempfile
from collections import Counter
from pathlib import Path

from cairn_mem.store import Store

LIMIT = 5  # fija: Recall@5 y Hit@3 se definen sobre el mismo top 5
CATEGORIES = ("lexical", "paraphrase", "multi", "no_answer")
WORD = re.compile(r"\w+", re.UNICODE)
# Lista propia del baseline: no comparte la del producto para no sesgar la comparación.
STOPWORDS = frozenset(
    {
        "a",
        "al",
        "con",
        "como",
        "cada",
        "de",
        "del",
        "el",
        "en",
        "es",
        "la",
        "las",
        "los",
        "mas",
        "muy",
        "o",
        "para",
        "por",
        "que",
        "se",
        "sin",
        "su",
        "sus",
        "un",
        "una",
        "y",
    }
)


def load(path: Path) -> tuple[list[dict], list[dict]]:
    entries = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    corpus = [entry for entry in entries if "title" in entry]
    queries = [entry for entry in entries if "query" in entry]
    return corpus, queries


def terms(query: str, drop_stopwords: bool = False) -> list[str]:
    found = [term.lower() for term in WORD.findall(query)]
    if drop_stopwords:
        found = [term for term in found if term not in STOPWORDS]
    return found


def score(ranked: list[str], expected: list[str]) -> dict:
    """Hit@3 and MRR use the first relevant hit; Recall@5 counts expected docs
    inside the top 5 (multi-relevant queries have more than one)."""
    position = next(
        (index + 1 for index, title in enumerate(ranked) if title in expected), None
    )
    return {
        "hit3": int(position is not None and position <= 3),
        "recall5": len([title for title in ranked[:5] if title in expected])
        / len(expected),
        "rr": 1 / position if position else 0.0,
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for category in CATEGORIES:
        subset = [row for row in rows if row["category"] == category]
        if category == "no_answer":
            summary[category] = {
                "n": len(subset),
                "abstention": mean([float(row["abstained"]) for row in subset]),
            }
        else:
            summary[category] = {
                "n": len(subset),
                "hit3": mean([row["hit3"] for row in subset]),
                "recall5": mean([row["recall5"] for row in subset]),
                "mrr": mean([row["rr"] for row in subset]),
            }
    answerable = [row for row in rows if row["category"] != "no_answer"]
    summary["overall"] = {
        "n": len(answerable),
        "hit3": mean([row["hit3"] for row in answerable]),
        "recall5": mean([row["recall5"] for row in answerable]),
        "mrr": mean([row["rr"] for row in answerable]),
    }
    return summary


def grep_rank(corpus: list[dict], query: str, limit: int) -> list[str]:
    words = terms(query, drop_stopwords=True)
    scored = []
    for memory in corpus:
        text = " ".join(
            str(memory.get(key) or "") for key in ("title", "body", "why")
        ).lower()
        counts = Counter(WORD.findall(text))
        hits = sum(counts[word] for word in words)
        if hits:
            scored.append((hits, memory["title"]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [title for _, title in scored[:limit]]


def cairn_ranks(corpus: list[dict], queries: list[dict], limit: int) -> list[list[str]]:
    with tempfile.TemporaryDirectory(
        prefix="cairn-retrieval-", ignore_cleanup_errors=True
    ) as tmp:
        store = Store(str(Path(tmp) / ".cairn"))
        for memory in corpus:
            store.save(
                kind=memory["kind"],
                title=memory["title"],
                body=memory["body"],
                why=memory.get("why"),
            )
        return [
            [row["title"] for row in store.search(query["query"], limit=limit)]
            for query in queries
        ]


def evaluate(queries: list[dict], rankings: list[list[str]]) -> list[dict]:
    rows = []
    for query, ranked in zip(queries, rankings, strict=True):
        row = {
            "id": query["id"],
            "category": query["category"],
            "query": query["query"],
            "ranked": ranked,
        }
        if query["category"] == "no_answer":
            row["abstained"] = not ranked
        else:
            row.update(score(ranked, query["expect"]))
        rows.append(row)
    return rows


def report(path: Path, corpus: list[dict], queries: list[dict], systems: dict) -> None:
    print(
        f"S6 retrieval benchmark (no LLM): {path.name}, "
        f"{len(corpus)} memories, {len(queries)} queries"
    )
    print("top-5 ranking, Hit@3 over the same order\n")
    header = f"{'category':<12}{'n':>4}{'system':>7}{'Hit@3':>8}{'R@5':>8}{'MRR':>8}"
    print(header)
    print("-" * len(header))
    for category in CATEGORIES:
        for name, summary in systems.items():
            values = summary[category]
            if category == "no_answer":
                abstained = round(values["abstention"] * values["n"])
                print(
                    f"{category:<12}{values['n']:>4}{name:>7}"
                    f"   abstained {abstained}/{values['n']}"
                )
            else:
                print(
                    f"{category:<12}{values['n']:>4}{name:>7}"
                    f"{values['hit3']:>8.2f}{values['recall5']:>8.2f}"
                    f"{values['mrr']:>8.2f}"
                )
    print("-" * len(header))
    for name, summary in systems.items():
        values = summary["overall"]
        print(
            f"{'overall':<12}{values['n']:>4}{name:>7}"
            f"{values['hit3']:>8.2f}{values['recall5']:>8.2f}{values['mrr']:>8.2f}"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).resolve().parent / "retrieval.jsonl"
    parser.add_argument("--file", type=Path, default=default)
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(argv)

    corpus, queries = load(ns.file)
    cairn_rows = evaluate(queries, cairn_ranks(corpus, queries, LIMIT))
    grep_rows = evaluate(
        queries,
        [grep_rank(corpus, query["query"], LIMIT) for query in queries],
    )
    systems = {
        "cairn": summarize(cairn_rows),
        "grep": summarize(grep_rows),
    }

    if ns.json:
        print(
            json.dumps(
                {
                    "dataset": str(ns.file),
                    "memories": len(corpus),
                    "queries": len(queries),
                    "summary": systems,
                    "rows": {"cairn": cairn_rows, "grep": grep_rows},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    report(ns.file, corpus, queries, systems)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
