# S6: honest retrieval benchmark

**Goal.** Measure retrieval before touching the ranking. The old precision@3 test uses a
30-query golden set built from the same words as the titles, so it can only return 1.00.
It proves the search works, not that it discriminates.

**Scope.** A new dataset (`bench/retrieval.jsonl`) and a measurement script
(`bench/bench_retrieval.py`). No product code, no ranking change, no new dependency.

## Dataset

- 52 memories in 5 families (auth, data, deploy, frontend, process), with deliberate
  confusables: two OAuth callbacks, two cache entries, two hash entries, three Git rules.
- 37 queries in 4 categories:
  - `lexical` (12): technical terms copied from a memory.
  - `paraphrase` (10): the same intent with different words.
  - `multi` (7): several memories are relevant (`expect` has more than one title).
  - `no_answer` (8): nothing is stored about the topic; 3 of them share a term with a
    stored memory, 5 share none.

Multi labels include every memory a human would call relevant, even if FTS cannot reach
it. For example, `tokens` expects the refresh-token memory, the CSRF token and the CSS
design tokens.

## Metrics

- **Hit@3**: a relevant memory appears in the top 3.
- **Recall@5**: share of the expected titles inside the top 5 (multi-relevant queries).
- **MRR**: 1 / rank of the first relevant memory.
- **Abstention**: share of `no_answer` queries that return zero results.

Fair baseline: literal grep with word boundaries. Query terms (stopwords dropped) are
counted over title, body and why; results are ordered by count. No stemming, no weights.

`tests/test_retrieval_bench.py` guards the dataset (unique titles and ids, valid kinds,
expected titles exist) and the metric math (a miss cannot score as a hit; abstention is
averaged, not counted as success).

## Acceptance criteria

- At least 40 memories and 30 queries; every expected title exists.
- Hit@3, Recall@5, MRR and abstention for cairn and grep.
- `pytest` and `ruff` clean.
- Real numbers written in `docs/BENCHMARKS.md`.
- Ranking, L0 and save rules untouched.

## Evidence (2026-11-08, updated after S6.1 on 2026-11-09)

Before the query-side fix, cairn scored 0.97 / 0.95 / 0.93 (overall Hit@3 / R@5 / MRR)
and matched grep. These are the current numbers:

| Category | n | System | Hit@3 | R@5 | MRR |
|---|---|---|---|---|---|
| lexical | 12 | cairn | 1.00 | 1.00 | 1.00 |
| lexical | 12 | grep | 1.00 | 1.00 | 1.00 |
| paraphrase | 10 | cairn | 0.90 | 1.00 | 0.88 |
| paraphrase | 10 | grep | 0.90 | 0.90 | 0.85 |
| multi | 7 | cairn | 1.00 | 1.00 | 1.00 |
| multi | 7 | grep | 1.00 | 0.95 | 1.00 |
| no_answer | 8 | cairn | abstained 5/8 | | |
| no_answer | 8 | grep | abstained 5/8 | | |
| overall | 29 | cairn | 0.97 | 1.00 | 0.96 |
| overall | 29 | grep | 0.97 | 0.95 | 0.95 |

- Lexical queries cannot separate the systems: both are exact-term lookups.
- The query-side fix ([S6.1](query-stemming-stopwords.md)) closes the plural gap:
  `tokens` reaches `token` and Recall@5 rises to 1.00. Cairn now edges grep on MRR.
- The remaining paraphrase miss is morphological in the other direction: `caducan` does
  not reach `caducidad`, and `enlaces` still puts the Cookies memory above magic links.
  FTS5 prefix matching only grows a token; it does not stem verbs.
- Abstention is 5/8. The system abstains only when every term is absent. The AND→OR
  fallback answers `terraform state locking`, `kafka consumer lag` and `kubernetes
  ingress tls` with a partial match. A two-root quorum was measured and rejected: it
  lifted abstention to 8/8 but cut paraphrase Hit@3 from 0.90 to 0.40.

## Decision

Do not touch the ranking. A 29-query set cannot justify new weights, and the baseline
does not lose. Stemming and stopwords were fixed on the query side; verb families and
abstention stay in the backlog with this measurement. S7 (incremental sync) is unchanged.

**Limit:** 52 memories, one author, and queries written from the corpus. The lexical
category reuses title terms on purpose. These numbers are indicative, not a closed
benchmark.
