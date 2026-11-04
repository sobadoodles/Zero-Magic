"""Simple keyword search over document chunks."""

import re

from app.document_chunks import normalize_for_search


def search_words(text):
    """Get unique, normalized words while keeping Persian half-spaces."""
    normalized = normalize_for_search(text).casefold()
    return set(re.findall(r"[\w\u200c]+", normalized))


def search_chunks(chunks, query):
    """Return matching chunks, with the most matching words first."""
    query_words = search_words(query)
    ranked = []

    for chunk in chunks:
        chunk_words = search_words(chunk["text"])
        score = len(query_words & chunk_words)

        if score > 0:
            ranked.append((score, chunk))

    # Python's sort keeps the original order when scores are equal.
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [chunk for score, chunk in ranked]