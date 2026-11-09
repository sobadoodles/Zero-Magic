"""Rank document chunks using vector similarity."""

import math


def cosine_similarity(first, second):
    """Measure how closely two vectors point in the same direction."""
    if len(first) != len(second):
        raise ValueError("Vectors must have the same number of dimensions.")

    dot_product = sum(a * b for a, b in zip(first, second))
    first_length = math.sqrt(sum(value * value for value in first))
    second_length = math.sqrt(sum(value * value for value in second))

    if first_length == 0 or second_length == 0:
        raise ValueError("Cannot compare a zero-length vector.")

    return dot_product / (first_length * second_length)


def rank_chunks(chunks, vectors, query_vector, limit=5):
    """Return the chunks closest to the query vector."""
    if len(chunks) != len(vectors):
        raise ValueError("Each chunk must have one vector.")

    if limit < 0:
        raise ValueError("Limit cannot be negative.")

    ranked = []

    for chunk, vector in zip(chunks, vectors):
        score = cosine_similarity(vector, query_vector)
        ranked.append((score, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [chunk for score, chunk in ranked[:limit]]


def save_index(path, chunks, vectors, *, model_name):
    """Save chunks and their vectors to a new JSON file."""
    import json
    from pathlib import Path

    if len(chunks) != len(vectors):
        raise ValueError("Each chunk must have one vector.")

    # FastEmbed returns NumPy values; convert them to ordinary Python floats.
    plain_vectors = [
        [float(value) for value in vector]
        for vector in vectors
    ]

    data = {
        "model": model_name,
        "chunks": chunks,
        "vectors": plain_vectors,
    }

    # Prepare the JSON before creating the file.
    text = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2)

    # "x" prevents accidentally overwriting an existing index.
    with Path(path).open("x", encoding="utf-8") as file:
        file.write(text + "\n")


def load_index(path):
    """Read a saved JSON index."""
    import json
    from pathlib import Path

    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)