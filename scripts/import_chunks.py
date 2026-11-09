"""Load chunks.json (and optionally a vector index.json) into the knowledge library.

Run with the server STOPPED, after owner setup. Never trusts stored
text_normalized fields — the server side always recomputes it.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import knowledge, storage  # noqa: E402
from app.document_chunks import normalize_for_search  # noqa: E402
from app.semantic_search import MODEL_NAME, load_index  # noqa: E402


def read_chunks(path):
    chunks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(chunks, list) or not chunks:
        raise SystemExit("The chunks file must be a non-empty list of labelled chunks.")
    for chunk in chunks:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("source"), str) \
                or not isinstance(chunk.get("text"), str) or not chunk["text"].strip():
            raise SystemExit("Every chunk needs a source and non-blank text.")
        if len(chunk["text"]) > knowledge.MAX_CHUNK_TEXT:
            raise SystemExit(f"A chunk from {chunk['source']} exceeds {knowledge.MAX_CHUNK_TEXT} characters. Re-ingest the document.")
    return chunks


def attach_vectors(chunks, index_path):
    index = load_index(index_path)
    if index.get("model") != MODEL_NAME:
        raise SystemExit(f"The index uses {index.get('model')!r}, but the app expects {MODEL_NAME!r}. Rebuild it with scripts/index_documents.py.")
    if len(index.get("chunks", [])) != len(chunks) or len(index.get("vectors", [])) != len(chunks):
        raise SystemExit("The index and the chunks file disagree about the chunk list. Rebuild the index from this exact chunks file.")
    return index["vectors"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chunks_file", type=Path)
    parser.add_argument("--index", type=Path, help="Optional vector index built from the same chunks file")
    parser.add_argument("--replace", action="store_true", help="Rebuild sources that are already in the library")
    args = parser.parse_args()

    chunks = read_chunks(args.chunks_file)
    vectors = attach_vectors(chunks, args.index) if args.index else None

    sources = []
    grouped = {}
    for chunk in chunks:
        name = chunk["source"].strip()
        if not knowledge.SOURCE_PATTERN.match(name):
            raise SystemExit(f"Unsupported source name: {name!r}")
        if name not in grouped:
            grouped[name] = []
            sources.append(name)
        grouped[name].append(chunk)

    existing = [name for name in sources if name in storage.doc_files]
    if existing and not args.replace:
        raise SystemExit("Already in the library: " + ", ".join(sorted(existing))
                         + ". Re-run with --replace to rebuild their passages.")

    reused_total = sum(1 for key in storage.doc_chunks if storage.doc_chunks[key]["source"] in set(existing))
    projected = len(storage.doc_chunks) - reused_total + len(chunks)
    if len(storage.doc_files) - len(existing) + len(sources) > knowledge.MAX_DOCUMENTS:
        raise SystemExit(f"The library holds at most {knowledge.MAX_DOCUMENTS} documents.")
    if projected > knowledge.MAX_TOTAL_CHUNKS:
        raise SystemExit(f"This would exceed {knowledge.MAX_TOTAL_CHUNKS} stored passages.")

    with storage.connection() as probe:
        owner = probe.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    ingested_by = owner[0] if owner else 0  # 0 marks pre-account imports; the UI still allows owner removal.

    now = datetime.now(timezone.utc).isoformat()
    ordinal_by_source = {}
    with storage.transaction() as db:
        # Replaced sources lose their old passages first.
        for name in existing:
            del storage.doc_files[name]
            for key in [key for key in storage.doc_chunks if storage.doc_chunks[key]["source"] == name]:
                del storage.doc_chunks[key]
        vector_rows = []
        for position, chunk in enumerate(chunks):
            name = chunk["source"].strip()
            ordinal_by_source[name] = ordinal_by_source.get(name, 0) + 1
            key = knowledge.chunk_id(name, ordinal_by_source[name])
            storage.doc_chunks[key] = {
                "id": key, "source": name,
                "page": chunk.get("page"), "heading": chunk.get("heading") or None,
                "text": chunk["text"], "text_normalized": normalize_for_search(chunk["text"]),
                "ordinal": ordinal_by_source[name],
            }
            if vectors is not None:
                vector_rows.append((key, json.dumps({"model": MODEL_NAME,
                                                     "vector": [float(value) for value in vectors[position]]})))
        for name in sources:
            pages = [c.get("page") for c in grouped[name] if isinstance(c.get("page"), int)]
            suffix = Path(name).suffix.lower().lstrip(".")
            storage.doc_files[name] = {
                "source_name": name,
                "format": suffix if suffix in ("pdf", "docx") else "pdf",
                "page_count": max(pages) if pages else None,
                "chunk_count": len(grouped[name]),
                "characters": sum(len(c["text"]) for c in grouped[name]),
                "ingested_by": ingested_by,
                "ingested_at": now,
            }
        if vectors is not None:
            # Only this import's own vectors are rewritten; other documents keep theirs.
            imported_keys = {row[0] for row in vector_rows}
            stale = [row[0] for row in db.execute("SELECT chunk_id FROM doc_vectors") if row[0] in imported_keys]
            db.executemany("DELETE FROM doc_vectors WHERE chunk_id=?", [(key,) for key in stale])
            db.executemany("INSERT INTO doc_vectors VALUES (?,?)", vector_rows)

    print(f"Imported {len(sources)} document(s), {len(chunks)} passages"
          + (f" with {len(chunks)} vectors" if vectors is not None else "")
          + f", into {storage.DB_PATH}.")
    print("Start the app. Review them under Documents, and turn the Library toggle on in Plan with AI.")


if __name__ == "__main__":
    main()
