"""Small sample files built in code, so tests never need files from outside."""

import io

import docx


def _pdf_string(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return b"(" + escaped.encode("cp1252") + b")"


def _text_stream(text: str) -> bytes:
    commands = [b"BT", b"/F1 12 Tf", b"14 TL", b"72 720 Td"]
    for number, line in enumerate(text.split("\n")):
        if number:
            commands.append(b"T*")
        commands.append(_pdf_string(line) + b" Tj")
    commands.append(b"ET")
    return b"\n".join(commands)


def make_pdf(pages: list[str | None], title: str | None = None, author: str | None = None) -> bytes:
    """Build a small PDF. Each page shows its text, and None makes a page without text."""
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    kids = []
    next_id = 4
    for text in pages:
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        kids.append(b"%d 0 R" % page_id)
        stream = b"" if text is None else _text_stream(text)
        objects[content_id] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id
        )
    objects[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(kids), len(kids))
    info = b""
    if title is not None:
        info += b"/Title " + _pdf_string(title)
    if author is not None:
        info += b" /Author " + _pdf_string(author)
    info_id = None
    if info:
        info_id = next_id
        objects[info_id] = b"<< " + info + b" >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for object_id in sorted(objects):
        offsets[object_id] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (object_id, objects[object_id])
    xref_at = len(out)
    size = max(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for object_id in range(1, size):
        out += b"%010d 00000 n \n" % offsets[object_id]
    trailer = b"<< /Size %d /Root 1 0 R" % size
    if info_id is not None:
        trailer += b" /Info %d 0 R" % info_id
    out += b"trailer\n" + trailer + b" >>\nstartxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)


def make_docx(paragraphs: list[str], title: str | None = None, author: str | None = None) -> bytes:
    """Build a small DOCX file with the given paragraphs."""
    document = docx.Document()
    document.core_properties.title = title or ""
    document.core_properties.author = author or ""
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
