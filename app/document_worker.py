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


def clean(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = ''.join(c for c in text if c in '\n\t' or (c.isprintable() and c != '\x00'))
    return re.sub(r'\n{4,}', '\n\n\n', text).strip()


def bounded(text):
    text = clean(text)
    if len(text) > MAX_TEXT:
        raise DocumentError('Extracted text exceeds 18,000 characters. Import a smaller document or paste only the first-release requirements. Nothing was truncated.')
    return text


def pdf_text(data):
    from pypdf import PdfReader
    if not data.startswith(b'%PDF-'):
        raise DocumentError('This file is not a valid PDF. Export it as PDF again.')
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise DocumentError('Password-protected PDFs are not supported. Export an unlocked copy first.')
    count = len(reader.pages)
    if count > 50:
        raise DocumentError('Use a PDF with no more than 50 pages.')
    blocks, empty = [], 0
    for i, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents and len(contents.get_data()) > 8 * 1024 * 1024:
            raise DocumentError('This PDF page is too complex. Export a simpler, smaller PDF.')
        text = clean(page.extract_text() or '')
        if text:
            blocks.append(f'[Page {i}]\n{text}')
            bounded('\n\n'.join(blocks))
        else:
            empty += 1
    if not blocks:
        raise DocumentError('No readable text was found. This PDF may be scanned and need OCR. Paste the text or import a text-based PDF instead.')
    warnings = ['PDF reading order can differ from the layout. Review tables and columns before saving.']
    if empty:
        warnings.append(f'{empty} page(s) had no extractable text; they may be blank or need OCR. Image-only content was not imported.')
    return {'text': bounded('\n\n'.join(blocks)), 'page_count': count, 'warnings': warnings}


def docx_text(data):
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
    def walk(element):
        if element.tag == W + 'p':
            text = clean(runs(element))
            if text:
                blocks.append(text)
                bounded('\n\n'.join(blocks))
            return
        if element.tag != W + 'del':
            for child in element:
                walk(child)
    walk(body)
    text = bounded('\n\n'.join(blocks))
    if not text:
        raise DocumentError('No readable text was found. Image-only Word documents need OCR or pasted text.')
    return {'text': text, 'page_count': None, 'warnings': ['Imported body paragraphs and table-cell text only. Images, headers, footers, comments, and formatting are not imported. Review the text before saving.']}


def extract(data, suffix):
    if not data or len(data) > MAX_BYTES:
        raise DocumentError('Choose a non-empty document no larger than 2 MB.')
    if suffix == '.pdf':
        return pdf_text(data)
    if suffix == '.docx':
        return docx_text(data)
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
        result = extract(sys.stdin.buffer.read(MAX_BYTES + 1), sys.argv[1])
        print(json.dumps({'ok': True, **result}, ensure_ascii=True))
    except DocumentError as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
    except Exception:
        print(json.dumps({'ok': False, 'error': 'The document could not be read safely. It may be damaged or too complex. Export a simpler PDF/.docx or paste its text.'}))


if __name__ == '__main__':
    main()
