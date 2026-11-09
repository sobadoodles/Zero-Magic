"""Search a saved document index by semantic similarity."""

import argparse
import sys

from app.semantic_search import load_index, rank_chunks
from scripts.index_documents import MODEL_NAME


def search_index(index, question, model, limit=5):
    """Embed a question and rank the saved chunks."""
    question_vector = next(model.embed([question]))
    return rank_chunks(
        index["chunks"],
        index["vectors"],
        question_vector,
        limit=limit,
    )


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Search a vector index.")
    parser.add_argument("index_file", help="Path to the saved index")
    parser.add_argument("question", help="Question to search for")
    args = parser.parse_args()

    if not args.question.strip():
        parser.error("Enter a question.")

    try:
        index = load_index(args.index_file)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(f"Could not read the index: {error}")

    if (
        not isinstance(index, dict)
        or index.get("model") != MODEL_NAME
        or not isinstance(index.get("chunks"), list)
        or not isinstance(index.get("vectors"), list)
        or len(index["chunks"]) != len(index["vectors"])
    ):
        parser.error("The index is invalid or uses a different model.")

    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=MODEL_NAME)
    results = search_index(index, args.question, model)

    if not results:
        print("The index contains no passages.")
        return

    print("Closest passages (check whether they answer the question):")

    for chunk in results:
        page = chunk.get("page")
        page_label = str(page) if page is not None else "not available"

        print(f"\nSource: {chunk['source']} | Page: {page_label}")
        if chunk.get("heading"):
            print(f"Heading: {chunk['heading']}")
        print(chunk["text"])


if __name__ == "__main__":
    main()