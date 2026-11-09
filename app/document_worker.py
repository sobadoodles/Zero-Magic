"""Bounded text extraction worker. Run as a child process; never stores uploads."""
import io
import json
import re
import sys
import zipfile

MAX_TEXT = 18000
MAX_BYTES = 2 * 1024 * 1024
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class DocumentError(ValueError):
    pass


def emit(payload):
    """Write JSON as UTF-8 bytes so Persian text does not depend on the console code page."""
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def clean(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = ''.join(
        c for c in text
        if c in '\n\t\u200c\u00a0' or (c.isprintable() and c != '\x00')
    )
    return re.sub(r'\n{4,}', '\n\n\n', text).strip()


def bounded(text):
    text = clean(text)
    if len(text) > MAX_TEXT:
        raise DocumentError('Extracted text exceeds 18,000 characters. Import a smaller document or paste only the first-release requirements. Nothing was truncated.')
    return text


def flatten_space(text):
    return re.sub(r"\s+", " ", text).strip()


def pdf_lines_with_sizes(page):
    """Build lines with font size and y position from the pypdf visitor.

    Returns None when the page cannot be visited (simple fakes, broken content),
    so callers fall back to layout text with no structure claims.
    """
    try:
        segments = []

        def visitor(text, cm, tm, font_dict, font_size):
            if text:
                segments.append((text, float(font_size or 0), float(tm[5])))

        page.extract_text(visitor_text=visitor)
    except Exception:
        return None

    if not segments:
        return None

    lines = []
    for text, size, y in segments:
        for part_index, part in enumerate(re.split(r"[\r\n]+", text)):
            if lines and part_index == 0 and abs(lines[-1][2] - y) <= 0.5:
                lines[-1][0] += part
                lines[-1][1] = max(lines[-1][1], size)
            else:
                lines.append([part, size, y])
    return [(part[0], part[1], part[2]) for part in lines if part[0].strip()]


def page_height(page):
    try:
        return float(page.mediabox.height)
    except Exception:
        return 0.0


def body_font_size(all_lines):
    sizes = {}
    for lines in all_lines:
        for _, size, _ in lines:
            if size > 0:
                sizes[round(size, 1)] = sizes.get(round(size, 1), 0) + 1
    if not sizes:
        return 0.0
    return max(sorted(sizes), key=lambda size: sizes[size])


def find_margin_furniture(pages_lines, page_heights):
    """Repeated short lines near the top/bottom of most pages: headers and footers.

    Conservative: needs three or more pages so a two-page title is never deleted.
    """
    furniture = set()
    count = len(pages_lines)
    if count < 3 or not any(heights for heights in page_heights):
        return furniture
    seen_on = {}
    for index, (lines, height) in enumerate(zip(pages_lines, page_heights)):
        if not height:
            continue
        for text, _, y in lines:
            if y >= height * 0.88 or y <= height * 0.12:
                key = flatten_space(text).casefold()
                if key and len(key) <= 90:
                    seen_on.setdefault(key, set()).add(index)
    for key, pages in seen_on.items():
        if len(pages) >= 3 and len(pages) >= count * 0.75:
            furniture.add(key)
    return furniture


def is_heading_line(text, size, body_size):
    return bool(
        body_size
        and size - body_size >= 1.5
        and size >= body_size * 1.15
        and 0 < len(text.strip()) <= 90
    )


def build_sections_from_lines(lines, furniture, body_size):
    """Rebuild heading sections and paragraphs from positioned lines.

    Paragraphs break on vertical gaps clearly larger than the body font. Text is
    joined from line order, so multi-column PDFs can read wrong — review before saving.
    """
    gap = max(body_size * 2.0, 18.0)
    sections = [{"heading": None, "paragraphs": []}]
    previous_y = None
    heading_pending = False

    def flush_paragraph():
        sections[-1]["paragraphs"].append([])

    for text, size, y in lines:
        stripped = text.strip()
        if not stripped or flatten_space(stripped).casefold() in furniture:
            continue
        if is_heading_line(stripped, size, body_size):
            if sections[-1]["heading"] is not None or sections[-1]["paragraphs"]:
                sections.append({"heading": stripped, "paragraphs": []})
            else:
                sections[-1]["heading"] = stripped
            previous_y = None
            heading_pending = True
            continue
        if heading_pending or previous_y is None or abs(previous_y - y) > gap:
            flush_paragraph()
            heading_pending = False
        if not sections[-1]["paragraphs"]:
            flush_paragraph()
        sections[-1]["paragraphs"][-1].append(stripped)
        previous_y = y

    built = []
    for section in sections:
        paragraphs = [" ".join(paragraph) for paragraph in section["paragraphs"] if paragraph]
        text = "\n\n".join(paragraphs)
        if section["heading"] or text:
            built.append({"heading": section["heading"], "text": text})
    return built or [{"heading": None, "text": ""}]


def pdf_text(data, include_pages=False):
    from pypdf import PdfReader

    if not data.startswith(b'%PDF-'):
        raise DocumentError('This file is not a valid PDF. Export it as PDF again.')

    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise DocumentError(
            'Password-protected PDFs are not supported. Export an unlocked copy first.'
        )

    count = len(reader.pages)
    if count > 50:
        raise DocumentError('Use a PDF with no more than 50 pages.')

    raw_pages = []
    for i, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents and len(contents.get_data()) > 8 * 1024 * 1024:
            raise DocumentError(
                'This PDF page is too complex. Export a simpler, smaller PDF.'
            )
        raw_pages.append((i, page, page.extract_text() or ''))

    blocks, pages, empty = [], [], 0
    pages_with_nulls = []

    for i, _, raw_text in raw_pages:
        if '\x00' in raw_text:
            pages_with_nulls.append(i)
        text = clean(raw_text)
        if text:
            blocks.append(f'[Page {i}]\n{text}')
            bounded('\n\n'.join(blocks))
        else:
            empty += 1

    if not blocks:
        raise DocumentError(
            'No readable text was found. This PDF may be scanned and need OCR. '
            'Paste the text or import a text-based PDF instead.'
        )

    warnings = [
        'PDF reading order can differ from the layout. Review tables and columns before saving.'
    ]
    if pages_with_nulls:
        page_numbers = ', '.join(str(number) for number in pages_with_nulls)
        warnings.append(
            f'PDF text may be corrupted: null characters were found on '
            f'page(s) {page_numbers}. Compare the extracted text with the original.'
        )
    if empty:
        warnings.append(
            f'{empty} page(s) had no extractable text; they may be blank or need OCR. '
            'Image-only content was not imported.'
        )

    if include_pages:
        all_lines = [pdf_lines_with_sizes(page) for _, page, _ in raw_pages]
        heights = [page_height(page) for _, page, _ in raw_pages]
        usable = all(lines is not None for lines in all_lines) and any(all_lines)
        body_size = body_font_size(all_lines) if usable else 0.0
        furniture = find_margin_furniture(all_lines, heights) if usable else set()
        heading_count = 0
        for position, (i, _, raw_text) in enumerate(raw_pages):
            text = clean(raw_text)
            if not text:
                continue
            entry = {"page": i, "text": text}
            lines = all_lines[position]
            if usable and lines:
                sections = build_sections_from_lines(lines, furniture, body_size)
                heading_count += sum(1 for section in sections if section["heading"])
                rebuilt = "\n\n".join(
                    f"{section['heading']}\n{section['text']}".strip()
                    for section in sections if section["heading"] or section["text"]
                )
                entry["sections"] = sections
                entry["text"] = clean(rebuilt) or text
            else:
                # Without reliable positioned lines, claim no structure at all.
                entry["sections"] = [{"heading": None, "text": text}]
            pages.append(entry)
        if furniture:
            warnings.append('Removed repeated header/footer lines found near the page margins.')
        if heading_count:
            warnings.append(
                f'PDF headings detected from font sizes (body {body_size:g}pt). '
                'Verify structure against the original before saving.'
            )

    result = {
        'text': bounded('\n\n'.join(blocks)),
        'page_count': count,
        'warnings': warnings,
    }
    if include_pages:
        result['pages'] = pages
    return result

def docx_text(data, include_sections=False):
    from defusedxml import ElementTree
    if not data.startswith(b'PK\x03\x04'):
        raise DocumentError('This is not a valid .docx file. Old .doc files are not supported.')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or len({e.filename for e in entries}) != len(entries):
            raise DocumentError('This Word file has too many or duplicate entries. Export a simpler .docx.')
        if any(e.flag_bits & 1 for e in entries):
            raise DocumentError('Encrypted Word files are not supported.')
        if sum(e.file_size for e in entries) > 20 * 1024 * 1024:
            raise DocumentError('This Word document expands beyond the safe size limit.')
        names = {e.filename for e in entries}
        if '[Content_Types].xml' not in names or 'word/document.xml' not in names:
            raise DocumentError('The file is not a Word .docx document.')
        if any('vbaproject' in n.casefold() for n in names):
            raise DocumentError('Macro-enabled Word documents are not supported. Export a plain .docx.')
        info = archive.getinfo('word/document.xml')
        if info.file_size > 4 * 1024 * 1024:
            raise DocumentError('The Word document text is too complex. Split it into smaller documents.')
        root = ElementTree.fromstring(archive.read(info), forbid_dtd=True)
    body = root.find(W + 'body')
    if body is None:
        raise DocumentError('The Word document body is missing.')

    def runs(element):
        if element.tag == W + 'del':
            return ''
        if element.tag == W + 't':
            return element.text or ''
        if element.tag == W + 'tab':
            return '\t'
        if element.tag in (W + 'br', W + 'cr'):
            return '\n'
        return ''.join(runs(child) for child in element)

    blocks = []
    sections = []
    current_heading = None
    section_blocks = []

    def finish_section():
        if current_heading is not None or section_blocks:
            sections.append({
                "heading": current_heading,
                "text": "\n\n".join(section_blocks),
            })

    def walk(element):
        nonlocal current_heading, section_blocks

        if element.tag == W + 'p':
            text = clean(runs(element))
            if text:
                blocks.append(text)
                bounded('\n\n'.join(blocks))

                if include_sections:
                    style = element.find(f'{W}pPr/{W}pStyle')
                    style_id = style.get(W + 'val', '') if style is not None else ''

                    if re.fullmatch(r'Heading[1-9]', style_id, re.IGNORECASE):
                        finish_section()
                        current_heading = text
                        section_blocks = []
                    else:
                        section_blocks.append(text)
            return

        if element.tag != W + 'del':
            for child in element:
                walk(child)

    walk(body)

    if include_sections:
        finish_section()

    text = bounded('\n\n'.join(blocks))
    if not text:
        raise DocumentError(
            'No readable text was found. Image-only Word documents need OCR or pasted text.'
        )

    result = {
        'text': text,
        'page_count': None,
        'warnings': [
            'Imported body paragraphs and table-cell text only. Images, headers, '
            'footers, comments, and formatting are not imported. Review the text '
            'before saving.'
        ],
    }
    if include_sections:
        result['sections'] = sections
    return result


def extract(data, suffix, *, include_pages=False):
    if not data or len(data) > MAX_BYTES:
        raise DocumentError('Choose a non-empty document no larger than 2 MB.')

    if suffix == '.pdf':
        return pdf_text(data, include_pages=include_pages)

    if suffix == '.docx':
        result = docx_text(data, include_sections=include_pages)
        if include_pages:
            result['pages'] = [{
                "page": None,
                "text": result['text'],
                "sections": result.pop('sections'),
            }]
        return result

    raise DocumentError('Use a .pdf or .docx file. Old .doc files are not supported.')

def main():
    try:
        # Unix only. Windows still has byte, ZIP, page, text and wall-time limits.
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        except ImportError:
            pass
        suffix = sys.argv[1]
        structured = '--structure' in sys.argv[2:]
        result = extract(sys.stdin.buffer.read(MAX_BYTES + 1), suffix, include_pages=structured)
        emit({'ok': True, **result})
    except DocumentError as error:
        emit({'ok': False, 'error': str(error)})
    except Exception:
        emit({'ok': False, 'error': 'The document could not be read safely. It may be damaged or too complex. Export a simpler PDF/.docx or paste its text.'})


if __name__ == '__main__':
    main()
