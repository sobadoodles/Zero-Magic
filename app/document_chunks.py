"""Split extracted document text into labeled chunks."""

import re

def chunk_page(source_name, page, text):
    # Keep single line breaks; split on blank lines.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r"\n(?:[ \t]*\n)+", text)

    # These labels are a conservative rule for the sample PDF.
    pdf_label = re.compile(
        r"^[ \t]*(?:goal|users|first release|acceptance|out of scope|reminder rule|permission rule|failure handling)[ \t]*:",
        re.IGNORECASE,
    )

    parts = []
    for paragraph in paragraphs:
        if page is None:
            parts.append(paragraph)
            continue

        lines = []
        for line in paragraph.split("\n"):
            if pdf_label.match(line) and lines:
                parts.append("\n".join(lines))
                lines = []
            lines.append(line)

        if lines:
            parts.append("\n".join(lines))

    chunks = []
    for part in parts:
        part = part.strip(" \t\n")
        if part:
            chunks.append({
                "source": source_name,
                "page": page,
                "heading": None,
                "text": part,
            })

    return chunks


def chunk_document(source_name, extracted):
    chunks = []

    for page in extracted["pages"]:
        if "sections" not in page:
            # Pages without heading metadata (older/unsupported extraction).
            chunks.extend(
                chunk_page(source_name, page["page"], page["text"])
            )
            continue

        for section in page["sections"]:
            heading = section["heading"]
            section_chunks = chunk_page(
                source_name,
                page["page"],
                section["text"],
            )

            # Preserve a heading even if it has no body text.
            if not section_chunks and heading:
                section_chunks = chunk_page(
                    source_name,
                    page["page"],
                    heading,
                )

            for chunk in section_chunks:
                chunk["heading"] = heading

            chunks.extend(section_chunks)

    # Store the original text plus a normalized companion: Persian forms of
    # Arabic letters and digits, so retrieval works without rewriting the source.
    for chunk in chunks:
        chunk["text_normalized"] = normalize_for_search(chunk["text"])

    return chunks

def normalize_for_search(text):
    # Normalize Arabic yeh and kaf to their Persian forms.
    translations = {
        0x064A: "\u06cc",  # ي → ی
        0x0643: "\u06a9",  # ك → ک
    }

    # Normalize Arabic-Indic and Persian digits to 0–9.
    for digit in range(10):
        translations[0x0660 + digit] = str(digit)
        translations[0x06F0 + digit] = str(digit)

    return text.translate(translations)
