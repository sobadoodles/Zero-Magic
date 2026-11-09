# Zero Magic — document QA with citations and failure collection

This adds the answering layer on top of the knowledge library: a command-line
question-answering tool that uses ONLY your stored passages, cites them, compares
keyword vs semantic retrieval, and writes down every failure it observes — exactly the
"most wrong answers start before any model is called" exercise.

## 1. Install

No new packages, no key changes. Branch: `feat/document-retrieval`. With the server
STOPPED and `.venv` active:

```powershell
Set-Location "C:\Zero Magic Project"
python scripts/backup_database.py
python -m pytest -q        # 242 tests, offline
```

New files: `scripts/answer_questions.py`, `eval/questions.json`,
`tests/test_document_qa.py`, `docs/specs/document-qa.md`, this guide. Changed:
`.gitignore` (ignores `eval/results/`). No database changes.

## 2. Put passages in the library (once)

Either through the **Documents** dialog in the browser, or from your Week-4 artifacts:

```powershell
python -m scripts.import_chunks "data\week4-review-chunks-v4.json" --index "data\week4-vector-index.json"
```

The `--index` part loads the 11 matching vectors so **semantic** retrieval can run.
Without it the QA tool still works and honestly marks semantic as "skipped: no embedded
passages".

## 3. Try retrieval-only first (free, no Groq)

```powershell
python -m scripts.answer_questions eval\questions.json --no-answering
```

Read the table: per question you get the gold-passage rank in each mode
(`K/S ranks`), the retrieval overlap, and a verdict such as
`semantic-only-gold — the multilingual embeddings found what keywords missed`.
Artifacts land in `eval/results/qa-<timestamp>/` (`results.json`, `failures.md`).

## 4. Now the grounded answers (uses your Groq key)

```powershell
python -m scripts.answer_questions eval\questions.json
```

Each question is answered twice — once from keyword-retrieved passages, once from
semantic ones — with the strict contract: ONLY the passages, `[K1]` citation per claim,
and a plain "The documents do not contain the answer…" when they don't
(`q_email_provider` is exactly that probe: reminders are in-app, no provider is named).
If the key isn't configured or the provider fails, the question records `skipped`
instead of making anything up.

## 5. What failures look like

`failures.md` groups every observed case by question and mode:

- **retrieval miss** — the gold passage never made the top-K
- **retrieved but ignored** — gold was in context yet uncited and unmatched, or the
  model denied an answer the passage holds
- **unsupported citation** — the cited passages don't contain the claim's key words
  (≥60% token check, deterministic)
- **hallucinated citation / answered-without-citation / hallucination** — ids that were
  never provided, uncited confidence, or answering an intentionally unanswerable question

plus a mode-comparison list. Iterate like Week 4 taught: read them, fix the worst ones
by improving chunking/questions, rerun. `--strict` makes failures fail the exit code if
you want to wire it into a checklist.

## 6. Write your own questions

`eval/questions.json` — ≤40 items of `{id, question, expected_found, gold}`. `gold`
matches by source + page + a required phrase (Persian/Arabic letter and digit forms are
linked automatically), so you can paste phrase fragments from the Documents review
screen. Add a question per requirement you care about, and one expected-miss per gap
you know the document has. `q_persian_who` shows the pattern: ask in Persian about
English text and watch keyword fail while the multilingual embedding succeeds.

## 7. Limits and honesty notes

- This CLI is READ-ONLY: it never writes the library/board database and has no approval
  powers. Run it while the server is stopped (or point `--db` at a private copy).
- The citation-support check is a mechanical token proxy, not semantic verification —
  a fluent-but-wrong answer can pass it. The failure list is evidence for your eyes,
  not an auto-grader.
- Keyword mode needs no model; semantic lazy-loads MiniLM (first use may download it);
  answers use your configured Groq models and can consume quota.
- The bundled `Team-Task-Reminders.pdf` has intentionally corrupted Persian lines
  (its own note says so) — that is a real ingestion failure case worth keeping in view.

## What comes next

Not here: hybrid reranking (merge both modes into one passage list before answering),
per-sentence citation enforcement beyond the token proxy, eval over more documents,
promoting observed failures into follow-up cards on the board (the loop closes nicely —
a "fix chunking" card from each retrieval miss), and a live server /api/v1/knowledge/qa
route. Those stay on the roadmap; this deliverable is the measurement instrument.
