# Document retrieval contract

## Goal
Turn extracted documents into reviewed, labelled passages that live in the workspace
database, and let the planning assistant quote them with visible citations. Nothing is
saved or sent to a model without an explicit human action at each step.

## Extraction with structure
- `POST /api/v1/documents/structure` (authenticated, same-origin JSON): input is the same
  `{filename, content_base64}` as `/extract`; extra fields rejected; same size/type guards.
- Output: `{source_name, format, page_count, warnings, chunks, chunk_count, total_characters}`.
  Each chunk = `{page, heading, text}`. No library writes, no model call, no brief saved.
- PDF structure comes from the pypdf text visitor (line text, font size, y position):
  headings are lines at least 1.5pt and 15% larger than the body font, ≤90 characters.
  Repeated short lines in the top 12%/bottom 12% margins on at least 3 pages and 75% of
  pages are removed as running headers/footers (never applied below 3 pages).
  Paragraphs break on vertical gaps beyond max(2× body size, 18pt).
- If positioned lines cannot be read (unusual readers/fakes), `sections` fall back to
  one heading-less block per page: no structure is invented.
- DOCX keeps the existing heading-style section capture. `text` of every page stays in
  layout order; structured mode notes line-order risk in warnings.
- Every chunk carries `text_normalized`: server-side Persian normalization (Arabic letter
  and digit forms mapped, half-space preserved). The original `text` is never rewritten.

## Library
- `POST /api/v1/knowledge` = `{documents: [{source_name, format pdf|docx, page_count,
  chunks: [{page, heading, text}] }], replace: bool}`. ≤20 documents/request, ≤800 chunks
  per document, ≤2500 characters per chunk, ≤60 documents and ≤3000 passages in total.
  `text_normalized` is always recomputed server-side. Existing source requires
  `replace:true` (409 otherwise; replace rebuilds only the named sources' passages).
- `GET /api/v1/knowledge` = shared summaries with `embedded_chunks`.
- `GET /api/v1/knowledge/{source}` = all passages in ordinal order.
- `DELETE /api/v1/knowledge/{source}` = importer or workspace owner only; passages go with
  it and their vectors are pruned in the same transaction.
- Original document bytes stay unpiped-to-child, never stored (unchanged `/extract` rule).

## Retrieval and embedding
- `POST /api/v1/knowledge/search` = `{query, limit 1–10, mode keyword|semantic}`.
  Keyword mode intersects normalized word sets (half-space aware) and returns match counts.
  Semantic mode requires vectors and loads fastembed lazily; missing/unloadable model → 503,
  no vectors → 409. Retrieval text is untrusted data for display, never instructions.
- `POST /api/v1/knowledge/embed` = `{force: bool}`: embeds passages without vectors (or all
  with force) using `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, storing
  `{model, vector}` per passage. One run at a time per process (429 busy). A failed embed
  leaves existing vectors untouched.
- `scripts/import_chunks.py chunks.json [--index index.json] [--replace]` loads offline
  week-4 artifacts with the same validation and server-side normalization. Run only with
  the server stopped.

## Assistant citations
- Chat accepts `use_knowledge: bool` (ignored for `assign`). Top-5 keyword passages for the
  latest user message are appended as a labelled `[Kn]` data block; passages count toward
  the existing combined size cap (413 above 48k). Every chat response now includes
  `citations: [{id, source, page, heading, excerpt≤300}]` (empty when unused).
- The model is instructed to cite `[Kn]` ids for passage-based sentences; the UI renders
  expandable citation chips. Approvals stay separate: passages can never confirm a proposal,
  and the proposal/confirm rules are unchanged.

## Boundaries
- Same login, CSRF/host, single-worker and SQLite snapshot assumptions as the rest of the app.
- Library content is shared with signed-in members, like briefs; it is not private storage
  and not an access-control boundary.
- Heading/footer detection is heuristic. The review screen exists because the human decides.
- The embedding model is downloaded on first embed (~80 MB) into the local cache.
- Deleting passages does not undo chat answers already shown, and SQL deletion is not
  forensic erasure of backups or provider requests already made.
