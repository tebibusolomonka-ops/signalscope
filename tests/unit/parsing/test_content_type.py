import pytest

from signalscope.parsing.content_type import content_charset


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
