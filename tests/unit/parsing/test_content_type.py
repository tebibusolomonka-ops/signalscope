import pytest

from signalscope.parsing.content_type import content_charset, media_type


@pytest.mark.parametrize(
    ("content_type", "charset"),
    [
        ("text/plain; charset=utf-8", "utf-8"),
        ('text/html; charset="UTF-8"', "utf-8"),
        ("text/html;charset=latin-1", "iso8859-1"),
        ("text/plain; format=flowed; charset=windows-1252", "cp1252"),
        ("text/plain", None),
        ("text/plain; charset=made-up", None),
        ("", None),
    ],
)
def test_content_charset(content_type: str, charset: str | None) -> None:
    assert content_charset(content_type) == charset


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("text/plain", "text/plain"),
        ("Text/HTML; charset=utf-8", "text/html"),
        ("  application/pdf  ", "application/pdf"),
        ("application/json;charset=utf-8;foo=bar", "application/json"),
        ("", ""),
    ],
)
def test_media_type(content_type: str, expected: str) -> None:
    assert media_type(content_type) == expected
