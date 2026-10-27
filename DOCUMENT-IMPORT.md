# PDF and Word brief import

This is a small patch for the working saved-brief version, including the Add brief popup fix.
Keep requirements-prd.txt unchanged. This update adds requirements-documents.txt; it is not a full replacement for your project's base dependencies.

## Install safely on Windows

Use your existing activated .venv in C:\Zero Magic Project. Back up first:

```powershell
python scripts/backup_database.py
```

Stop Uvicorn with Ctrl+C. If you have not already created the branch:

```powershell
git switch -c feat/document-import
```

Extract the ZIP OUTSIDE the project, then merge its app/, frontend/, tests/, docs/ and examples/ files into matching folders. Replace only matching files; do not replace entire folders.

Changed files: app/main.py, frontend/app.js, frontend/index.html.
New files: app/documents.py, app/document_worker.py, requirements-documents.txt, tests/test_documents.py, this guide, docs/specs/document-import.md, and two sample briefs under examples/document-import/.

Keep data/, .env, .venv, .git, frontend/styles.css and frontend/vendor/ unchanged. No database migration/reset, account setup, old import/export procedure, or new API key is needed.
If you changed the same source files yourself, review the diff before replacing them.

Install the new parsers into the EXISTING environment:

```powershell
python -m pip install -r requirements-documents.txt
```

Run the focused checks (using the isolated tests/conftest.py delivered with the PRD update):

```powershell
python -m pytest tests/test_documents.py tests/test_prds.py tests/test_persistent_workspace.py -q
```

Do not run tests against your live workspace database. The provided conftest selects a temporary database before importing the app. Older unauthenticated tests may still need updating; do not remove login protections to fix their 401 errors.

Launch:

```powershell
python -m uvicorn app.main:app --reload
```

Open your usual localhost/127.0.0.1 address, Ctrl+F5, then sign in normally.

## Try it

1. Plan with AI -> Add brief -> Load file.
2. Choose examples/document-import/sample-brief.pdf.
3. Wait for extraction. Review the text, including the [Page 1] marker. It is NOT saved yet.
4. Try sample-brief.docx too. Confirm replacing the unsaved draft if asked.
5. Edit the extracted text as needed, then Save and use brief.
6. Discuss, Preview cards, approve creation, then approve assignments separately, as before.

Extraction does not call Groq, save a brief, create cards, assign anyone, or modify the board. Only Save and use brief persists text to SQLite. That saved text is shared with signed-in teammates. When you later discuss/generate cards, selected brief text is sent to your configured Groq model as before. Do not include secrets.

## What is supported

- Text-based PDF: up to 2 MB, up to 50 pages. Pages are labeled in the extracted text.
- Word .docx: up to 2 MB. Body paragraphs and table-cell text, in document order.
- Existing UTF-8 .txt/.md: read in the browser, up to 64 KB.
- All briefs: max 18,000 characters. Oversized extraction is rejected, not silently truncated.
- Short extracted text can be edited; saved briefs still require at least 80 characters.

## Limits and clear errors

- Scanned/image-only documents: no OCR in this update. If a PDF has no readable text, it returns an OCR-needed message. A partially readable PDF warns about pages with no extractable text; review it for missing requirements.
- PDF reading order/tables/columns may be imperfect. Compare extracted text with the original before saving.
- .docx images, headers, footers, comments, and formatting are not imported. Deleted tracked-change text is excluded; inserted text can appear. This is not a perfect Word rendering engine.
- Old .doc, .docm, encrypted/password-protected files, malformed files, and macro packages are rejected. Export an unlocked plain .docx or text-based PDF instead. Microsoft Word is not required on the server.
- Errors leave the current draft untouched. Successful import replaces it only after confirming when there are unsaved edits. Canceling that prompt keeps the draft too.
- Loading and saving controls are disabled during import, so you cannot save half-extracted text. Closing the popup during extraction is blocked until the bounded request completes.
- A 429 means wait: at most 3 import attempts/minute/account and two simultaneous parser processes. Throttle state is process-local and resets with the server. Failed attempts count too.
- Extraction has a 12-second wall-time limit; complex documents can fail. Split or simplify them rather than increasing all limits.

## Storage and implementation

PDF/.docx bytes are sent as base64 JSON to the signed-in Python server, not to Groq. The app passes bytes through a pipe to a short-lived parser process. It does not write the original document to an upload folder or database. No URLs, external relationships, macros, or document scripts are followed/executed by the importer. This is text extraction, not an antivirus or production upload sandbox.

The endpoint checks streamed request size, extension and file signature. Word ZIP entry/expansion limits and DTD/entity rejection protect the XML path. The child parser has Unix memory/CPU limits plus the cross-platform wall timeout; Windows does not have the extra Unix resource limits. Child environment variables are restricted and do not include the Groq API key.

Continue using exactly one Uvicorn worker with the existing SQLite snapshot implementation. This is a local learning-project importer, not a production deployment guide. Keep dependencies updated and backups private.

## What comes next

This implements document-to-brief text extraction. It does NOT implement labeled retrieval chunks, embeddings, document search, citations, OCR, persistent original-file attachments, or AI replanning edits to existing cards. Those are separate next steps in Week 3.
