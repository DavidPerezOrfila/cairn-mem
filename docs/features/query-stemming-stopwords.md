# S6.1: query-side stemming and stopwords

**Goal.** Turn the two S6 findings into a measurable search improvement without touching
the index, the schema or the BM25 weights: plural queries must reach singular memories,
and filler words must not decide the result.

**Scope.** `Store.search` only. The FTS index and `SCHEMA_VERSION` stay the same; no
rebuild is needed.

## Change

- **Plural to singular on the query side.** FTS5 prefix matching only grows a token, so
  `tokens`* never reached `token` and `enlaces`* never reached `enlace`. The query now
  trims `-es` (7+ characters) or `-s` (6+ characters) before adding `*`. The 5-character
  floor is measured: with a 4-character floor, `redis` became `redi` and matched
  `redirect_uri`, a new false positive.
- **Stopwords dropped** before building the `AND`/`OR` expression (Spanish and English).
  A query made only of stopwords returns nothing instead of matching every memory.

## Rejected: quorum of two terms

The planned fallback required at least two matching roots so that only one leftover term
could not answer a query. Measured on S6, it costs more than it fixes:

| Variant | Hit@3 | R@5 | MRR | Paraphrase Hit@3 | Abstention |
|---|---|---|---|---|---|
| AND then OR (before) | 0.97 | 0.95 | 0.93 | 0.90 | 5/8 |
| Quorum of 2 roots | 0.79 | 0.79 | 0.79 | 0.40 | 8/8 |
| 2 roots or a 5+ character root | 0.97 | 1.00 | 0.94 | 0.90 | 7/8 |
| Stemming plus stopwords (shipped) | 0.97 | 1.00 | 0.96 | 0.90 | 5/8 |

Rows 2-3 come from this build by swapping only the fallback expression: pairwise `AND`s
for the two-root quorum, and long roots plus pairs for the middle variant. Row 1 is the
S6 baseline before the query-side fix.

Terse paraphrases (`la replica va por detras del primario`) reduce to one real term.
Requiring two drops five correct results to abstain on three synthetic no-answer queries.
The middle variant recovers recall but hides behind a length threshold (`state` passes,
`lag` and `tls` do not), which is arbitrary and would also filter valid short acronyms.
Abstention stays in the backlog; it needs a calibrated mechanism, not a term count.

## Acceptance criteria

- A failing test for plural-to-singular and stopwords.
- Full suite and `ruff` clean.
- End-to-end and internal SLOs still pass.
- S6 numbers measured before and after.
- No schema change and no `setup` vocabulary.

## Evidence (2026-11-09)

`python bench/bench_retrieval.py` after the change:

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

- Recall@5 goes from 0.95 to 1.00: every expected memory now enters the top 5.
- MRR goes from 0.93 to 0.96; cairn edges the grep baseline on ordering.
- The remaining paraphrase miss is still morphological (`caducan` vs `caducidad`, verb
  forms) plus the Cookies false hit for `enlaces`: the stem fixes the plural, not the
  word family.
- **Limit:** the 5-character floor leaves 5-character plurals (`tests`, `boxes`)
  untrimmed, so `tests` does not reach a body that says `test`. A 4-character floor
  caused a worse false positive (`redis` → `redi` → `redirect_uri`).
