import io

import pytest
from pypdf import PdfReader, PdfWriter

from signalscope.parsing import pdf_document
from signalscope.parsing.pdf_document import PdfDocumentParser
from signalscope.parsing.types import DocumentParsingError, ParsedDocument


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


def parse(data: bytes) -> ParsedDocument:
    return PdfDocumentParser().parse(data, content_type="application/pdf", filename="report.pdf")


def test_text_of_one_page() -> None:
    document = parse(make_pdf(["Hello from a PDF."]))

    assert document.text == "Hello from a PDF."
    assert document.metadata == {"page_count": 1, "truncated": False}


def test_pages_are_read_in_order() -> None:
    document = parse(make_pdf(["First page", "Second page\nwith two lines", "Third page"]))

    assert document.text == "First page\n\nSecond page\nwith two lines\n\nThird page"
    assert document.metadata["page_count"] == 3


def test_title_and_author_come_from_the_metadata() -> None:
    document = parse(make_pdf(["Body"], title="  Annual   Report ", author="Jane Doe"))

    assert document.title == "Annual Report"
    assert document.metadata == {"page_count": 1, "truncated": False, "author": "Jane Doe"}


def test_title_is_never_guessed() -> None:
    # Neither the first line nor the file name becomes the title.
    assert parse(make_pdf(["Big Heading\nBody text"])).title is None


def test_non_ascii_text() -> None:
    assert parse(make_pdf(["Café crème"])).text == "Café crème"


def test_pdf_without_text_gives_empty_text() -> None:
    # Like a scanned document: pages exist, but there is no text layer.
    document = parse(make_pdf([None, None], title="Scan"))

    assert document.text == ""
    assert document.title == "Scan"
    assert document.metadata["page_count"] == 2


def test_punctuation_alone_is_not_text() -> None:
    assert parse(make_pdf(["- . -", "*"])).text == ""


def test_pages_without_text_are_skipped() -> None:
    assert parse(make_pdf(["One", None, "Three"])).text == "One\n\nThree"


def test_encrypted_pdf_is_rejected() -> None:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["Secret"]))))
    writer.encrypt(user_password="secret", algorithm="RC4-128")
    encrypted = io.BytesIO()
    writer.write(encrypted)

    with pytest.raises(DocumentParsingError, match="PDF is encrypted."):
        parse(encrypted.getvalue())


@pytest.mark.parametrize("data", [b"", b"not a pdf at all", b"%PDF-1.4\n%%EOF", b"\x00" * 64])
def test_broken_pdf_is_rejected(data: bytes) -> None:
    with pytest.raises(DocumentParsingError, match="Document is not a readable PDF."):
        parse(data)


def test_large_pdf_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    data = make_pdf(["Hello"])
    monkeypatch.setattr(pdf_document, "MAX_PDF_BYTES", len(data) - 1)

    with pytest.raises(DocumentParsingError, match="PDF is larger than"):
        parse(data)


def test_pages_past_the_limit_are_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_document, "MAX_PAGES", 2)

    document = parse(make_pdf(["One", "Two", "Three"]))

    assert document.text == "One\n\nTwo"
    assert document.metadata == {"page_count": 3, "truncated": True}


def test_broken_page_does_not_hide_other_pages(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    original = pdf_document.PageObject.extract_text
    calls = []

    def extract_text(self: pdf_document.PageObject, *args: object, **kwargs: object) -> str:
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("bad content stream")
        return original(self)

    monkeypatch.setattr(pdf_document.PageObject, "extract_text", extract_text)

    document = parse(make_pdf(["One", "Two", "Three"]))

    assert document.text == "One\n\nThree"
    assert "Could not read the text of PDF page 2" in caplog.text
