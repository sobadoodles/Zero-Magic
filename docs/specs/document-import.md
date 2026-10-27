# Document import contract

POST /api/v1/documents/extract (authenticated, same-origin JSON)

Input: {filename: string, content_base64: string}. Extra fields are rejected.
Supported extensions: .pdf / .docx, case-insensitive. Filename <=150 chars, no paths/control characters.
Max decoded file: 2 MiB; max streamed JSON: 2,800,000 bytes.

200: {source_name, format, text, page_count, warnings}.
PDF page_count is an integer; DOCX page_count is null (pagination requires layout rendering).
No original bytes, brief IDs, card IDs or automatic writes in response.

401: not signed in; 403: cross-origin; 413: request/file too large;
415: unsupported format/content-type; 422: invalid document/empty extracted text/timeout/text too long;
429: account throttle or parser capacity.

PDF: 50 pages; text labeled [Page N]; encrypted documents rejected; no readable text -> OCR-needed error.
DOCX: read word/document.xml only, no archive extraction to disk; max 2000 entries, 20 MiB declared expansion, 4 MiB main XML; duplicates, encryption, VBA, DTD/entities rejected.
18,000-character output limit; never silently truncate. Short text can be reviewed/expanded before save.
12-second worker timeout; 2 concurrent worker slots; 3 attempts/minute/account (process-local).
Original bytes are piped, not persisted. Parsers do not perform model calls or open URLs.

UI: preserve the working single-modal Add brief fix. Busy state disables conflicting controls.
Failure/cancel keeps text/title/source; successful extraction becomes an UNSAVED editable draft.
Save continues through existing PRD validation/revisions. Card/assignment approval boundaries unchanged.

Tests cover auth, payload/size/type validation, real PDF/OOXML parsing, page labels, table text,
scan/encryption/macro/DTD failures, rate/capacity/timeout, explicit save and existing regressions.
Manual/browser QA also covers busy state, draft preservation, mobile widths and file selection.
