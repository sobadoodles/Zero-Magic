# Document QA contract — grounded CLI answers, comparisons, failures

## Goal
Answer questions ONLY from retrieved passages with source/page citations, say plainly
when the documents do not contain the answer, compare keyword vs semantic retrieval on
the same questions, and collect observed failures as a durable artifact.

## Deliverable
`python -m scripts.answer_questions eval/questions.json [--db PATH] [--top 5]
[--out eval/results] [--no-answering] [--strict]`
- Console table: gold rank and found-flags per mode, failure counts, comparison verdict.
- `eval/results/qa-<timestamp>/results.json` — per question: resolved gold chunk id,
  retrieved passages (id/source/page/preview), gold rank, parsed answer with citations,
  comparison notes, and every failure string.
- `.../failures.md` — failures grouped by question/mode, plus the mode-comparison list.

## Question set
`eval/questions.json` (≤40): `{id, question, expected_found, gold|null}`. `gold` is
`{source, page?, must_contain}` and is resolved against the library by normalized text
containment (Persian/Arabic letter and digit forms linked). `expected_found:false`
probes the plain "The documents do not contain the answer…" behavior.

## Grounding contract
Each mode's retrieved passages are labelled `[K1..Kn]` and sent as untrusted data with
one system rule: use ONLY those passages, cite every claim `[Kn]`, else `found=false`
with an answer beginning "The documents do not contain the answer". Answers pass through
`ask_structured` (Instructor re-ask) against the `GroundedAnswer` model:
found ⇒ answer + ≥1 citation; not-found ⇒ citations empty and plain statement required.
No board context, no approval powers, no writes: this CLI is read-only over the library.
Model/provider failure ⇒ that question's answering is recorded `skipped`, never invented.

## Failure taxonomy (mechanical, deterministic)
- retrieval miss — gold resolved but not in this mode's top-K
- gold not in library — the expectation names text no stored passage contains
- hallucinated citation — cited id was never provided
- answered without citation — found=true, no ids
- retrieved but ignored — gold was in context yet neither cited nor reflected, or the
  model denied an answer the gold passage clearly holds
- unsupported citation — claim's key words (≥60% of significant tokens) absent from the
  answer plus cited passages
- hallucination — expected not-found question answered with citations anyway

## Comparison
Per question: retrieval-set overlap (Jaccard), gold rank per mode, verdict
`keyword-first | semantic-first | semantic-only-gold | keyword-only-gold | both missed |
one mode unavailable`. A missing vector set or unavailable embedding model marks
semantic `skipped` — keyword results still run and compare honestly.

## Boundaries
Read-only against the SQLite library (run with the server stopped, or --db a copy).
Keyword retrieval needs no dependencies; semantic retrieval lazy-loads the shared
multilingual MiniLM (first run may download it). Groq quota is consumed only when
answering runs; --no-answering does a pure retrieval evaluation. Failures are evidence
for improving ingestion/questions — this update adds no automatic reranking, no
hybrid merge, and no live DB writes from evaluation.
