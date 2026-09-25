import json
from typing import Any

import pytest

from signalscope.parsing.json_document import MAX_DEPTH, MAX_VALUES, JsonParser
from signalscope.parsing.types import DocumentParsingError, ParsedDocument


def parse(data: bytes) -> ParsedDocument:
    return JsonParser().parse(data, content_type="application/json")


def parse_value(value: Any) -> ParsedDocument:
    return parse(json.dumps(value).encode())


def test_values_become_path_lines() -> None:
    document = parse_value(
        {
            "title": "Example",
            "author": {"name": "Jane", "email": None},
            "tags": ["ai", "media"],
            "published": True,
            "rating": 4.5,
            "views": 1200,
        }
    )

    assert document.text.splitlines() == [
        "title: Example",
        "author.name: Jane",
        "author.email: null",
        "tags[0]: ai",
        "tags[1]: media",
        "published: true",
        "rating: 4.5",
        "views: 1200",
    ]
    assert document.metadata == {"truncated": False}


def test_key_order_is_kept() -> None:
    assert parse(b'{"zebra": 1, "apple": 2, "mango": 3}').text == "zebra: 1\napple: 2\nmango: 3"


def test_nested_lists_and_objects() -> None:
    document = parse_value({"matrix": [[1, 2], [3]], "people": [{"name": "Ann", "age": 40}]})

    assert document.text.splitlines() == [
        "matrix[0][0]: 1",
        "matrix[0][1]: 2",
        "matrix[1][0]: 3",
        "people[0].name: Ann",
        "people[0].age: 40",
    ]


def test_top_level_list_and_value() -> None:
    assert parse(b'["a", {"b": false}]').text == "[0]: a\n[1].b: false"
    assert parse(b'"just text"').text == "just text"
    assert parse(b"42").text == "42"


def test_text_is_not_escaped() -> None:
    assert parse('{"name": "Zoë – 東京"}'.encode()).text == "name: Zoë – 東京"


def test_empty_containers_give_no_lines() -> None:
    assert parse(b"{}").text == ""
    assert parse(b'{"tags": [], "extra": {}, "name": "x"}').text == "name: x"


def test_byte_order_mark_is_allowed() -> None:
    assert parse(b'\xef\xbb\xbf{"a": 1}').text == "a: 1"


def test_title_comes_from_a_top_level_title() -> None:
    assert parse_value({"title": "  Report  ", "body": "x"}).title == "Report"
    assert parse_value({"title": ""}).title is None
    assert parse_value({"title": 5}).title is None
    assert parse_value({"meta": {"title": "Nested"}}).title is None
    assert parse_value(["title"]).title is None


@pytest.mark.parametrize(
    "data", [b"", b"{", b"{'single': 'quotes'}", b"[1, 2,]", b"NaN-ish", b"\xff\xfe\x00"]
)
def test_invalid_json_is_rejected(data: bytes) -> None:
    with pytest.raises(DocumentParsingError, match="Document is not valid JSON."):
        parse(data)


def test_values_past_the_depth_limit_are_left_out() -> None:
    value: Any = "deep"
    for _ in range(MAX_DEPTH + 5):
        value = {"a": value}
    shallow = {"a": {"b": "kept"}}

    document = parse_value([shallow, value])

    assert document.text == "[0].a.b: kept"
    assert document.metadata == {"truncated": True}


def test_value_at_the_depth_limit_is_kept() -> None:
    value: Any = "deep"
    for _ in range(MAX_DEPTH):
        value = {"a": value}

    document = parse_value(value)

    assert document.text == ".".join(["a"] * MAX_DEPTH) + ": deep"
    assert document.metadata == {"truncated": False}


def test_number_of_values_is_limited() -> None:
    document = parse_value(list(range(MAX_VALUES + 5)))

    lines = document.text.splitlines()
    assert len(lines) == MAX_VALUES
    assert lines[-1] == f"[{MAX_VALUES - 1}]: {MAX_VALUES - 1}"
    assert document.metadata == {"truncated": True}


def test_extremely_deep_nesting_is_rejected() -> None:
    with pytest.raises(DocumentParsingError, match="nested too deeply"):
        parse(b"[" * 200_000 + b"]" * 200_000)
