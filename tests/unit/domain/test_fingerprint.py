import re

from signalscope.domain.documents.fingerprint import content_fingerprint


def fingerprint(
    title: str | None = None, content: str | None = None, url: str | None = None
) -> str | None:
    return content_fingerprint(title=title, content=content, url=url)


def test_fingerprint_is_a_sha256_hex_digest() -> None:
    value = fingerprint("Title", "Body", "https://news.example/a")

    assert value is not None
    assert re.fullmatch(r"[0-9a-f]{64}", value)


def test_same_content_gives_the_same_fingerprint() -> None:
    assert fingerprint("Title", "Body", "https://news.example/a") == fingerprint(
        "Title", "Body", "https://news.example/a"
    )


def test_any_field_change_gives_a_new_fingerprint() -> None:
    original = fingerprint("Title", "Body", "https://news.example/a")

    assert fingerprint("Other title", "Body", "https://news.example/a") != original
    assert fingerprint("Title", "Other body", "https://news.example/a") != original
    assert fingerprint("Title", "Body", "https://news.example/b") != original


def test_fields_are_kept_apart() -> None:
    assert fingerprint("Title Body", None) != fingerprint("Title", "Body")
    assert fingerprint("Title", None) != fingerprint(None, "Title")


def test_line_endings_and_outer_whitespace_are_normalized() -> None:
    expected = fingerprint("Title", "Line one\nLine two")

    assert fingerprint("  Title\n", "Line one\r\nLine two") == expected
    assert fingerprint("Title", "\n Line one\rLine two  ") == expected


def test_inner_text_is_not_rewritten() -> None:
    assert fingerprint(None, "Line one\nLine two") != fingerprint(None, "Line one Line two")
    assert fingerprint(None, "two  spaces") != fingerprint(None, "two spaces")


def test_nothing_to_fingerprint_gives_none() -> None:
    assert fingerprint() is None
    assert fingerprint("  ", "\r\n", "") is None
