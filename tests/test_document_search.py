
def test_search_returns_matching_chunks_in_relevance_order():
    from app.document_search import search_chunks

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