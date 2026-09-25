import io

import pytest
from pypdf import PdfReader, PdfWriter

from sample_files import make_pdf
from signalscope.parsing import pdf_document
from signalscope.parsing.pdf_document import PdfDocumentParser
from signalscope.parsing.types import DocumentParsingError, ParsedDocument


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
