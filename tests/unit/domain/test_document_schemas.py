import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from signalscope.domain.documents.model import Document
from signalscope.domain.documents.schemas import DocumentCreate, DocumentRead

SOURCE_ID = uuid.uuid4()


def test_valid_document() -> None:
    document = DocumentCreate.model_validate(
        {
            "source_id": str(SOURCE_ID),
            "external_id": " guid-1 ",
            "url": " https://example.com/a ",
            "title": " An article ",
            "content": "  Text with spaces kept.  ",
            "language": "pt-BR",
            "published_at": "2026-03-01T12:30:00+02:00",
        }
    )

    assert document.source_id == SOURCE_ID
    assert document.external_id == "guid-1"
    assert document.url == "https://example.com/a"
    assert document.title == "An article"
    assert document.content == "  Text with spaces kept.  "
    assert document.language == "pt-br"
    assert document.published_at == datetime(2026, 3, 1, 10, 30, tzinfo=UTC)
    assert document.published_at.utcoffset() == timedelta(0)


def test_only_source_id_is_required() -> None:
    document = DocumentCreate.model_validate({"source_id": str(SOURCE_ID)})

    assert document.model_dump(exclude={"source_id"}) == {
        "external_id": None,
        "url": None,
        "title": None,
        "content": None,
        "language": None,
        "published_at": None,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": "not-a-uuid"},
        {"external_id": ""},
        {"external_id": "x" * 501},
        {"url": ""},
        {"url": "   "},
        {"url": "https://example.com/" + "x" * 2048},
        {"title": "   "},
        {"language": "   "},
        {"language": "x" * 36},
        {"published_at": "yesterday"},
        {"published_at": "2026-03-01T12:30:00"},
    ],
)
def test_invalid_document_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DocumentCreate.model_validate({"source_id": str(SOURCE_ID)} | changes)


def test_missing_source_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="source_id"):
        DocumentCreate.model_validate({"title": "An article"})


@pytest.mark.parametrize("field", ["id", "created_at", "updated_at"])
def test_client_cannot_set_server_fields(field: str) -> None:
    data = {"source_id": str(SOURCE_ID), field: "2026-01-01T00:00:00Z"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DocumentCreate.model_validate(data)


def test_read_schema_from_model() -> None:
    now = datetime.now(UTC)
    published_at = datetime(2026, 3, 1, 12, 30, tzinfo=timezone(timedelta(hours=2)))
    document = Document(
        id=uuid.uuid4(),
        source_id=SOURCE_ID,
        external_id="guid-1",
        url="https://example.com/a",
        title="An article",
        content=None,
        language="en",
        published_at=published_at,
        created_at=now,
        updated_at=now,
    )

    read = DocumentRead.model_validate(document)

    assert read.model_dump() == {
        "id": document.id,
        "source_id": SOURCE_ID,
        "external_id": "guid-1",
        "url": "https://example.com/a",
        "title": "An article",
        "content": None,
        "language": "en",
        "published_at": published_at,
        "created_at": now,
        "updated_at": now,
    }


@pytest.mark.parametrize(
    ("language", "expected"), [("EN", "en"), ("en-US", "en-us"), (" PT-BR ", "pt-br")]
)
def test_language_is_normalized(language: str, expected: str) -> None:
    document = DocumentCreate.model_validate({"source_id": str(SOURCE_ID), "language": language})

    assert document.language == expected
