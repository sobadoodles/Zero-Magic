"""Ingest trusted local PDF and DOCX files into labeled JSON chunks."""

import argparse
import json
from pathlib import Path

from app.document_chunks import chunk_document
from app.document_worker import MAX_BYTES, extract


def main():
    parser = argparse.ArgumentParser(
        description="Turn a folder of PDF and DOCX files into chunks."
    )
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not args.folder.is_dir():
        parser.error("The document folder does not exist.")

    if args.output.exists():
        parser.error("The output file already exists. Choose a new filename.")

    files = sorted(
        path for path in args.folder.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in (".pdf", ".docx")
    )
    if not files:
        parser.error("No PDF or DOCX files were found in the folder.")

    chunks = []

    for path in files:
        try:
            # Read at most one byte beyond the existing importer limit.
            with path.open("rb") as document:
                data = document.read(MAX_BYTES + 1)

            extracted = extract(data, path.suffix.lower(), include_pages=True)
            chunks.extend(chunk_document(path.name, extracted))

            for warning in extracted["warnings"]:
                print(f"{path.name}: {warning}")
        except Exception as error:
            parser.exit(1, f"Could not ingest {path.name}: {error}\n")

    try:
        # Exclusive creation prevents overwriting an existing file.
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(chunks, output, ensure_ascii=False, indent=2)
    except OSError as error:
        parser.exit(1, f"Could not write output: {error}\n")

    print(f"Saved {len(chunks)} chunks from {len(files)} documents.")


if __name__ == "__main__":
    main()