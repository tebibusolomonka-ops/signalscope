import pytest

from signalscope.domain.documents.language import normalize_language


@pytest.mark.parametrize(
    ("value", "expected"),
    [("en", "en"), ("EN", "en"), ("en-US", "en-us"), (" PT-BR ", "pt-br"), ("\tde\n", "de")],
)
def test_language_is_trimmed_and_lowercased(value: str, expected: str) -> None:
    assert normalize_language(value) == expected


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_blank_language_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="language must not be empty"):
        normalize_language(value)
