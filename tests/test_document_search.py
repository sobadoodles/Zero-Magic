
def test_search_rare_words_outrank_common_word_boilerplate():
    """The Day 19 IDF fix, pinned: with repeated boilerplate, a chunk carrying the
    rare informative words beats one that matched more total (common) words."""
    from app.document_search import search_chunks

    chunks = [
        {"source": "prd.pdf", "page": 1, "text": "The run of the agent run and the run."},
        {"source": "prd.pdf", "page": 2, "text": "Maximum Agent Turns 30 failed_turn_cap."},
        {"source": "prd.pdf", "page": 3, "text": "The agent run and the run ok."},
        {"source": "prd.pdf", "page": 4, "text": "The agent run and the run ok."},
        {"source": "prd.pdf", "page": 5, "text": "The agent run and the run ok."},
    ]
    results = search_chunks(chunks, "what is the maximum agent turns run and the run")
    assert results[0]["page"] == 2  # rare maximum/turns/30 outweigh four common matches


def test_search_ties_keep_document_order():
    from app.document_search import search_chunks

    chunks = [
        {"source": "a.pdf", "page": 1, "text": "reminder policy"},
        {"source": "b.pdf", "page": 2, "text": "reminder policy"},
    ]
    assert [c["source"] for c in search_chunks(chunks, "reminder policy")] == ["a.pdf", "b.pdf"]

    chunks = [
        {"source": "brief.pdf", "page": 1, "text": "Send a reminder."},
        {"source": "brief.pdf", "page": 2, "text": "Send a reminder before the due date."},
        {"source": "brief.pdf", "page": 3, "text": "Members can update their profile."},
    ]

    results = search_chunks(chunks, "reminder due date")

    assert results == [chunks[1], chunks[0]]


def test_search_normalizes_persian_letters_and_digits():
    from app.document_search import search_chunks

    chunk = {
        "source": "brief.docx",
        "page": None,
        "text": "شماره کتاب ۱۲۳",
    }

    # The query uses Arabic forms; the chunk uses Persian forms.
    results = search_chunks([chunk], "كتاب ١٢٣")

    assert results == [chunk]
    assert results[0]["text"] == "شماره کتاب ۱۲۳"

def test_search_cli_shows_source_page_and_text(tmp_path):
    import json
    import subprocess
    import sys

    chunks_file = tmp_path / "chunks.json"
    chunks_file.write_text(
        json.dumps([
            {
                "source": "brief.pdf",
                "page": 2,
                "heading": None,
                "text": "Send a reminder before the due date.",
            }
        ]),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.search_documents",
            str(chunks_file),
            "reminder",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert "brief.pdf" in result.stdout
    assert "2" in result.stdout
    assert "Send a reminder before the due date." in result.stdout