"""Keyword search over document chunks, weighted by inverse document frequency."""

import math
import re

from app.document_chunks import normalize_for_search


def search_words(text):
    """Get unique, normalized words while keeping Persian half-spaces."""
    normalized = normalize_for_search(text).casefold()
    return set(re.findall(r"[\w\u200c]+", normalized))


def search_chunks(chunks, query):
    """Return matching chunks, best first; ties keep document order.

    Rare words (30, failed_turn_cap, due) outweigh common ones (the, run, what):
    each matched word scores ln((N-df+0.5)/(df+0.5) + 1) — a chunk every document
    contains adds almost nothing, so long boilerplate no longer outscores a table
    row that literally answers the question.
    """
    query_words = search_words(query)
    total = len(chunks)
    doc_freq = {}
    word_sets = []
    for chunk in chunks:
        words = search_words(chunk["text"])
        word_sets.append(words)
        for word in words:
            doc_freq[word] = doc_freq.get(word, 0) + 1

    def idf(word):
        df = doc_freq.get(word, 0)
        return math.log((total - df + 0.5) / (df + 0.5) + 1.0)

    scored = []
    for index, (chunk, words) in enumerate(zip(chunks, word_sets)):
        matched = query_words & words
        if matched:
            scored.append((sum(idf(word) for word in matched), -index, chunk))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [chunk for score, index, chunk in scored]
