# Day 19 Deliverable: Groundedness Evaluation Report

## 1. Test Corpus & Setup
- **Reference document:** `Zero Magic Reference PRD.pdf` (`ZM-PRD-2026-04`) — 292,812 bytes, 4 pages →
  **44 stored passages**; extraction preserved **all clause tags `[C01]–[C18]`**, both tables and the
  roadmap callout; 8,954 characters (inside the 18,000-cap, no limit changes needed).
- **Ingestion path (real, not mocked):** `POST /api/v1/boards/{id}/documents` on a throwaway DB →
  `pending → processing → ready`, attempts 1, then `POST /api/v1/knowledge/embed` → 44/44 vectors
  (multilingual MiniLM). Board: one disposable "ZM Reference PRD" project; the workspace DB was untouched.
- **Evaluation set:** `eval/questions.json`-style 30 questions (`eval/day19/eval_questions.json`) —
  25 answerable with clause + keyword ground truth, 5 out-of-domain (`Q26–Q30`) expecting refusal.
- **Endpoint tested:** `POST /api/v1/boards/{id}/ask` (keyword mode, top-5, temperature 0).
  Retrieval scored independently from `POST /api/v1/knowledge/search` (same query/mode/limit).
- **Model:** Groq `openai/gpt-oss-20b`, automatic fallback to `gpt-oss-120b`. Free tier =
  8,000 TPM, so frequent 429s occurred; the app's fallback rescued every single call (server log:
  0 unanswered) and the harness backed off 12/30/60 s — no failures were counted as `provider`.
- **Harness:** `scripts/run_day19_evals.py` (cookie login, evidence-chunk cause attribution,
  `results-*.json` artifacts).

## 2. Baseline vs. Post-Fix Scores

| Metric | v1 as-delivered (flawed ruler) | Baseline v2 (fixed ruler) | Post-fix (IDF) | Delta baseline→fix |
| :--- | :--- | :--- | :--- | :--- |
| **Retrieval** (evidence chunk in top-5) | 25/25 (100%) * | 23/25 (92%) | **24/25 (96%)** | **+4%** |
| **Groundedness** (right chunk retrieved, cited, answer not refused) | 23/25 (92%) | 23/25 (92%) | **24/25 (96%)** | **+4%** |
| **Refusal** (clean plain not-found on Q26–Q30) | 5/5 (100%) | 5/5 (100%) | 5/5 (100%) | unchanged |

\* v1's 100% was an **overstatement**: its retrieval check accepted any *cited* text that merely
contained the clause substring, and its refusal/text-marker heuristics produced known false
negatives (see §3.2). We record it, then report v2 as the honest baseline.

## 3. Failure Analysis Grouped by Cause

### 3.1 Measurement fixes (done before touching the app — the plan demands trustworthy scores first)
1. **Refusal detection via fuzzy text markers misfired on `Q13`:** the model's *correct* answer
   ("…returns a plain not-found refusal directly **without** invoking the language model") was
   scored as a refusal because it contained the phrase "no relevant". Fix: trust the API's
   machine-readable `found` flag.
2. **Evidence location by substring matched `git` inside `Gitea`** (wrong evidence chunk for `Q01`).
   Fix: word-set membership using the same tokenizer as retrieval.
3. **Cause attribution impossible without stored retrieval sets:** v1's report couldn't say
   *which* chunk it retrieved. Fix: record `retrieved_ids` + `evidence_id` per question — the
   mislabelled "generation" bucket for `Q19` became correctly classified as **retrieval**.

### 3.2 True failure group at (v2) baseline: **RETRIEVAL — 2 cases**
- `Q19` (max agent turns) and `Q20` (wall-clock/cost budget) — both `[C15]` guardrail **table rows**.
- Root cause: the keyword scorer counted matches equally, so common query words ("run", "the",
  "and") in long boilerplate clauses outscored rare, informative tokens ("30", "turns",
  "failed_turn_cap") in the short table-row passages; ties kept document order, so rows 33–35
  lost to the `[C15]` lead-in and `[C14]`. Evidence chunks ranked **outside the top 10**.

### 3.3 Other groups
- Ingestion: 0 (all clause tags and table text reached the library).
- Generation: 0 true cases at v2 (the 2 "generation" hits in v1 were the measurement artifacts above).
- Refusal: 0 (all five probes declined cleanly, no invented citations).

## 4. Fix Implemented (one targeted fix, as required)
- **Targeted cause:** Retrieval (top group, 2 cases).
- **Change:** IDF-weighted scoring in `app/document_search.search_chunks` — each matched word
  scores `ln((N−df+0.5)/(df+0.5)+1)`, so boilerplate present in every passage adds ~nothing and
  rare tokens dominate; ties keep document order (stable). 20 lines, no new dependencies,
  no API change. Pinned by 2 new unit tests (boilerplate-vs-rare-word ranking; tie stability).
- **Verification (0-token, before spending any Groq quota):** evidence-chunk rank improved
  `Q19: outside top-10 → rank 3` (now inside top-5); `Q20: outside top-10 → rank 6`.
- **Verification (full re-run, same 30 questions, same ruler):** Retrieval **23→24/25**,
  Groundedness **23→24/25**, Refusal **5/5 held** — scores moved, no regressions
  (267 app tests pass; previously-passing questions Q01–Q18, Q21–Q30 all still pass).
- **Remaining known gap:** `Q20` by one rank position (6 at top-5). Next-cycle candidates,
  deliberately NOT bundled into this fix: (a) top-k 8 for ask (retrieval-only check confirms the
  chunk is inside 8), or (b) ingestion fix that keeps short table rows with their clause lead-in
  (the failure mode the reference report template predicted). Semantic mode (already wired) is a
  third option, untested against quota so far.

## 5. Files
- Harness: `scripts/run_day19_evals.py` · environment: `scripts/bootstrap_day19.py`
- Questions: `eval/day19/eval_questions.json` · Results: `eval/day19/results-{baseline,baseline-v2,postfix}.json`
- Fix: `app/document_search.py` (+ tests in `tests/test_document_search.py`)
- Repro: `python scripts/bootstrap_day19.py` → start server with its DB →
  `python scripts/run_day19_evals.py --base http://127.0.0.1:8123 --board <id> --user … --password …`
