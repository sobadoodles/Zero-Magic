"""Create a local vector index from document chunks."""

import argparse
import json
from pathlib import Path

from app.semantic_search import save_index


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def create_index(chunks, output_path, model):
    """Embed chunks and save them using the supplied model."""
    texts = [chunk["text"] for chunk in chunks]
    vectors = list(model.embed(texts))

    save_index(output_path, chunks, vectors, model_name=MODEL_NAME)


def main():
    parser = argparse.ArgumentParser(description="Index document chunks.")
    parser.add_argument("chunks_file", help="Path to the chunks JSON file")
    parser.add_argument("--output", required=True, help="New index file path")
    args = parser.parse_args()

    try:
        chunks = json.loads(
            Path(args.chunks_file).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.error(f"Could not read chunks: {error}")

    if not isinstance(chunks, list) or not chunks or any(
        not isinstance(chunk, dict)
        or not isinstance(chunk.get("source"), str)
        or not isinstance(chunk.get("text"), str)
        for chunk in chunks
    ):
        parser.error("Provide a non-empty list of labeled chunks.")

    if Path(args.output).exists():
        parser.error("Output file already exists. Choose a new filename.")

    # Import here so the unit test doesn't load or download a model.
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=MODEL_NAME)
    create_index(chunks, args.output, model)

    print(f"Saved an index for {len(chunks)} chunks to {args.output}.")


if __name__ == "__main__":
    main()