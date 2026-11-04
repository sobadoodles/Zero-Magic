"""Search a saved chunk file and show matching passages."""

import argparse
import json
import sys
from pathlib import Path

from app.document_search import search_chunks


def main():
    # Keep Persian text readable in redirected output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Search document chunks by keyword."
    )
    parser.add_argument("chunks_file", help="Path to the chunks JSON file")
    parser.add_argument("query", help="Words to search for")
    args = parser.parse_args()

    try:
        text = Path(args.chunks_file).read_text(encoding="utf-8")
        chunks = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.error(f"Could not read the chunks file: {error}")

    if not isinstance(chunks, list) or any(
        not isinstance(chunk, dict)
        or not isinstance(chunk.get("source"), str)
        or not isinstance(chunk.get("text"), str)
        for chunk in chunks
    ):
        parser.error("The chunks file must contain a list of labeled chunks.")

    results = search_chunks(chunks, args.query)

    if not results:
        print("No matching passages found.")
        return

    for chunk in results[:5]:
        page = chunk.get("page")
        page_label = str(page) if page is not None else "not available"

        print(f"\nSource: {chunk['source']} | Page: {page_label}")
        if chunk.get("heading"):
            print(f"Heading: {chunk['heading']}")
        print(chunk["text"])


if __name__ == "__main__":
    main()