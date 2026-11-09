# Zero Magic — knowledge library and cited answers

This update connects the Week-4 ingestion/search work to the app: documents become
reviewed, labelled passages in your SQLite workspace, and **Plan with AI** can quote them
with `[K1]`-style citations. No new provider account or key is needed. Embeddings run
locally with fastembed (already in your `.venv`).

## 1. Back up and install

```powershell
Set-Location "C:\Zero Magic Project"
python scripts/backup_database.py
```

Stop Uvicorn (Ctrl+C in its terminal). This update adds three new SQLite tables through
`app/storage.py` at startup — no reset, no export/import procedure, no manual migration.
Keep `.env`, `.venv`, `data/`, `backups/`, and `frontend/vendor/` untouched.

Files changed: `app/storage.py`, `app/document_worker.py`, `app/documents.py`,
`app/document_chunks.py`, `app/assistant.py`, `app/semantic_search.py`,
`scripts/index_documents.py`, `app/main.py`, `frontend/index.html`, `frontend/app.js`,
`frontend/styles.css`, `tests/test_document_chunks.py`.
New: `app/knowledge.py`, `scripts/import_chunks.py`, `tests/test_knowledge.py`,
`docs/specs/document-retrieval.md`, this guide.

Branch used here: `feat/document-retrieval`.

## 2. Run the checks

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

Expect **223 passed**. The suite uses a throwaway database, real synthetic PDFs/DOCX
through the parser subprocess, and faked models — no Groq calls, no model download.

## 3. Load your Week-4 practice documents (one time)

With the server stopped, reuse the artifacts you already produced (all three verified
during this update; 11+16 passages imported):

```powershell
python -m scripts.import_chunks "data\week4-review-chunks-v4.json" --index "data\week4-vector-index.json"
python -m scripts.import_chunks "data\week4-sample-chunks-v3.json"
```

(`--index` imports the matching vectors so semantic search works immediately; the index
file must have been built from that exact chunks file.) Or skip this and import fresh
files through the browser UI in step 5 — same result. Then start the app and sign in:

```powershell
python -m uvicorn app.main:app --reload
```

Open your usual address, press **Ctrl+F5**.

## 4. What changed on the board

- Header gained **Documents**: extract → review passages → save; remove; keyword search;
  **Embed for semantic search** (first run downloads the multilingual MiniLM once).
- Plan with AI gained **📚 Library off/on**. With it on, discussion answers quote relevant
  saved passages and each answer shows expandable `[K1]` citation chips (source · page ·
  heading). Approvals for cards/assignments are unchanged and stay separate from passages.
- Chat answers now also work for Persian documents written with Arabic letter forms:
  normalization is stored per passage at save time.

## 5. Try the full loop

1. **Documents → Extract file(s) for review** → pick `examples/document-import/sample-brief.pdf`.
   Read every passage: page numbers, headings, and the warnings line. Nothing is saved yet.
   Add several files at once; use **Skip this file** to drop one.
2. Tick **Replace same-named documents** only if you mean to rebuild an existing entry,
   then **Add to library**.
3. Click **Embed for semantic search** once, so meaning-based matching works too.
4. **Plan with AI → 📚 Library on** → ask something only your practice brief answers,
   e.g. "When should the reminder arrive and who may change the time?" The reply cites
   `[K1]`/`[K2]`; open a chip to read the exact passage.
5. **Preview cards** still behaves exactly as before: preview → approve creation →
   approve assignments. Knowledge passages only inform discussion text.
6. Restart Python and refresh: library, citations, and vectors all survive.

## 6. Ingestion quality notes (read before trusting structure)

- **PDF headings** are detected from font sizes (≥1.5pt and 15% above the body font).
  Scan the structure warning against the original; PDFs from odd exporters may mislabel.
- **Running headers/footers** are removed only on documents with **3+ pages** where the
  line repeats near the page margins on most pages. Your two-page practice brief keeps
  its "ZERO MAGIC – PRACTICE BRIEF" header — by design, so two-page titles are never eaten.
- A corrupted-text warning (null characters) fires when a PDF hides them — it fired on
  page 2 of `Team-Task-Reminders.pdf` during this update's verification. Compare with the
  original before saving.
- Scanned/image-only pages still say OCR is needed; this update does not add OCR.
- Word documents: headers/footers of `.docx` were never imported (body + tables only);
  heading styles are preserved as before.

## 7. Limits and expected errors

- Library: ≤60 documents, ≤3000 passages, ≤2500 characters per passage, ≤20 documents per
  save request. 409 with a clear remedy; re-imported names need `replace`.
- `/documents/structure` shares the `/extract` guards: 2 MB files, 12-second parser, two
  parser slots, 3 attempts/minute/account, 422s with plain-language messages.
- Semantic search before embedding → 409 "No embedded passages yet". Missing/blocked
  fastembed or a failed model load → 503; keyword search keeps working regardless.
- Embedding is single-flight per server process: a second request while one runs → 429.
- Chat with the Library on adds passages to the existing 48k combined-size cap → 413 asks
  you to shorten the discussion.
- Keep exactly one Uvicorn worker. Do not run `import_chunks.py` while the server runs.

## 8. Scope and safety

Passages are shared workspace data like briefs — visible to every signed-in member, never
private, and not a permissions boundary. Passage text (like board and PRD text) is
untrusted data: tests prove planted "SYSTEM:" instructions inside a document cannot create
cards, assign people, or confirm proposals. AI approvals remain manual and separate. The
first Embed run may download ~80 MB into your local model cache; after that everything is
offline. SQL deletion of a document removes active rows, not forensic remnants.

## 9. What comes next

Not included here: reranking/combining keyword+semantic results into one score, citations
inside PRD breakdowns (brief text already covers that path), automatic re-embedding when a
document is replaced, OCR, per-document privacy, a vector extension for SQLite, and any
production storage. Library answers are still only as good as the reviewed passages you
save — read them with your eyes first, like Week 4 taught.
