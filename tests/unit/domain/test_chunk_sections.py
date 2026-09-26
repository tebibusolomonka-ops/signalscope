from sample_files import make_pdf
from signalscope.domain.documents.chunking import TextChunk, chunk_document, chunk_text
from signalscope.parsing.pdf_document import PdfDocumentParser
from signalscope.parsing.types import SECTION_SEPARATOR, ParsedDocument, ParsedSection

# Small sizes keep the test texts readable.
SMALL = {"max_chars": 50, "overlap_chars": 10, "min_chars": 25}


def document_of(*texts: str, kind: str = "page") -> ParsedDocument:
    sections = tuple(
        ParsedSection(text=text, kind=kind, index=index, metadata={"page_number": index + 1})
        for index, text in enumerate(texts)
    )
    return ParsedDocument(text=SECTION_SEPARATOR.join(texts), sections=sections)


def section_ranges(document: ParsedDocument) -> list[tuple[int, int]]:
    ranges = []
    start = 0
    for section in document.sections:
        ranges.append((start, start + len(section.text)))
        start += len(section.text) + len(SECTION_SEPARATOR)
    return ranges


def check(document: ParsedDocument, chunks: list[TextChunk]) -> None:
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    ranges = section_ranges(document)
    for chunk in chunks:
        assert document.text[chunk.start_char : chunk.end_char] == chunk.text
        start, end = ranges[int(chunk.metadata["section_index"])]
        # A chunk lies inside its one section.
        assert start <= chunk.start_char and chunk.end_char <= end


def test_short_pages_become_one_chunk_each() -> None:
    document = document_of("Page one text.", "Page two text.")

    chunks = chunk_document(document)

    assert [(chunk.text, dict(chunk.metadata)) for chunk in chunks] == [
        ("Page one text.", {"page_number": 1, "section_kind": "page", "section_index": 0}),
        ("Page two text.", {"page_number": 2, "section_kind": "page", "section_index": 1}),
    ]
    check(document, chunks)


def test_chunks_never_cross_a_page() -> None:
    pages = [" ".join(f"p{page}w{word}" for word in range(30)) for page in range(3)]
    document = document_of(*pages)

    chunks = chunk_document(document, **SMALL)

    assert len(chunks) > 3
    check(document, chunks)
    for chunk in chunks:
        page = int(chunk.metadata["page_number"])
        assert all(word.startswith(f"p{page - 1}w") for word in chunk.text.split())


def test_offsets_point_into_the_whole_text() -> None:
    document = document_of("First page.", "Second page, somewhat longer.", "Third.")

    chunks = chunk_document(document)

    assert [chunk.start_char for chunk in chunks] == [
        0,
        len("First page.\n\n"),
        len("First page.\n\nSecond page, somewhat longer.\n\n"),
    ]
    check(document, chunks)


def test_document_without_sections_is_one_text() -> None:
    document = ParsedDocument(text="Plain text without sections.")

    assert chunk_document(document) == chunk_text(document.text)


def test_other_section_kinds() -> None:
    document = ParsedDocument(
        text="Intro.\n\nBackground\n\nDetails.",
        sections=(
            ParsedSection(text="Intro.", kind="section", index=0),
            ParsedSection(
                text="Background\n\nDetails.",
                kind="section",
                index=1,
                metadata={"heading": "Background"},
            ),
        ),
    )

    chunks = chunk_document(document)

    assert [dict(chunk.metadata) for chunk in chunks] == [
        {"section_kind": "section", "section_index": 0},
        {"heading": "Background", "section_kind": "section", "section_index": 1},
    ]
    check(document, chunks)


def test_real_pdf_pages() -> None:
    parsed = PdfDocumentParser().parse(
        make_pdf(["Alpha page.", None, "Gamma page."]), content_type="application/pdf"
    )

    chunks = chunk_document(parsed)

    assert [(chunk.text, chunk.metadata["page_number"]) for chunk in chunks] == [
        ("Alpha page.", 1),
        ("Gamma page.", 3),
    ]
    check(parsed, chunks)
