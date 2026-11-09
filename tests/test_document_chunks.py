from app.document_chunks import chunk_page


def test_pdf_paragraphs_keep_source_and_page():
    chunks = chunk_page(
        "brief.pdf",
        2,
        "Build a board.\n\nReject empty titles.",
    )

    assert chunks == [
        {
            "source": "brief.pdf",
            "page": 2,
            "heading": None,
            "text": "Build a board.",
        },
        {
            "source": "brief.pdf",
            "page": 2,
            "heading": None,
            "text": "Reject empty titles.",
        },
    ]


def test_word_chunk_has_no_invented_page():
    chunks = chunk_page("brief.docx", None, "A requirement.")

    assert chunks == [
        {
            "source": "brief.docx",
            "page": None,
            "heading": None,
            "text": "A requirement.",
        },
    ]


def test_word_chunks_keep_section_headings():
    from app.document_chunks import chunk_document

    extracted = {
        "pages": [{
            "page": None,
            "text": "Goal\n\nBuild a board.\n\nRules\n\nReject blank titles.",
            "sections": [
                {"heading": "Goal", "text": "Build a board."},
                {"heading": "Rules", "text": "Reject blank titles."},
            ],
        }],
    }

    chunks = chunk_document("brief.docx", extracted)

    assert chunks == [
        {
            "source": "brief.docx",
            "page": None,
            "heading": "Goal",
            "text": "Build a board.",
            "text_normalized": "Build a board.",
        },
        {
            "source": "brief.docx",
            "page": None,
            "heading": "Rules",
            "text": "Reject blank titles.",
            "text_normalized": "Reject blank titles.",
        },
    ]


def test_heading_without_body_is_not_lost():
    from app.document_chunks import chunk_document

    extracted = {
        "pages": [{
            "page": None,
            "text": "Summary",
            "sections": [{"heading": "Summary", "text": ""}],
        }],
    }

    chunks = chunk_document("brief.docx", extracted)

    assert chunks == [{
        "source": "brief.docx",
        "page": None,
        "heading": "Summary",
        "text": "Summary",
        "text_normalized": "Summary",
    }]

def test_search_normalizes_arabic_letters_and_digits():
    from app.document_chunks import normalize_for_search

    assert normalize_for_search("كتاب يكي ١٢٣ ۴۵۶") == "کتاب یکی 123 456"


def test_search_normalization_keeps_persian_half_space():
    from app.document_chunks import normalize_for_search

    assert normalize_for_search("می\u200cرود") == "می\u200cرود"

def test_pdf_labeled_sections_keep_continuation_lines():
    text = (
        "Team notification preferences\n"
        "Goal: Build a board.\n"
        "Users: Existing members of the workspace.\n"
        "They can update their preferences.\n"
        "Acceptance: Preferences survive a restart."
    )

    chunks = chunk_page("brief.pdf", 1, text)

    assert [chunk["text"] for chunk in chunks] == [
        "Team notification preferences",
        "Goal: Build a board.",
        "Users: Existing members of the workspace.\n"
        "They can update their preferences.",
        "Acceptance: Preferences survive a restart.",
    ]
    assert all(chunk["page"] == 1 for chunk in chunks)
    assert all(chunk["heading"] is None for chunk in chunks)


def test_pdf_reminder_rules_split_into_separate_chunks():
    from app.document_chunks import chunk_page

    text = (
        "Requirements & Persian sample\n"
        "Reminder rule: Send a reminder one day before.\n"
        "Use the workspace time zone.\n"
        "Permission rule: Only the owner can change the time.\n"
        "Failure handling: Record delivery failures."
    )

    chunks = chunk_page("brief.pdf", 2, text)

    assert [chunk["text"] for chunk in chunks] == [
        "Requirements & Persian sample",
        "Reminder rule: Send a reminder one day before.\n"
        "Use the workspace time zone.",
        "Permission rule: Only the owner can change the time.",
        "Failure handling: Record delivery failures.",
    ]
    assert all(chunk["page"] == 2 for chunk in chunks)
    assert all(chunk["source"] == "brief.pdf" for chunk in chunks)