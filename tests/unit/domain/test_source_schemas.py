import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.sources.schemas import SourceCreate, SourceRead


def test_valid_source() -> None:
    source = SourceCreate.model_validate(
        {"type": "rss", "name": "  Example feed  ", "url": "https://example.com/rss"}
    )

    assert source.type is SourceType.RSS
    assert source.name == "Example feed"
    assert source.url == "https://example.com/rss"


@pytest.mark.parametrize("source_type", ["upload", "api"])
def test_url_is_optional_for_some_types(source_type: str) -> None:
    source = SourceCreate.model_validate({"type": source_type, "name": "Example"})

    assert source.url is None


@pytest.mark.parametrize("source_type", ["web", "rss"])
def test_url_is_required_for_web_and_rss(source_type: str) -> None:
    with pytest.raises(ValidationError, match=f"url is required for {source_type} sources"):
        SourceCreate.model_validate({"type": source_type, "name": "Example"})


@pytest.mark.parametrize(
    "data",
    [
        {"type": "podcast", "name": "Example"},
        {"type": "upload", "name": ""},
        {"type": "upload", "name": "   "},
        {"type": "upload", "name": "x" * 201},
        {"type": "web", "name": "Example", "url": ""},
        {"type": "web", "name": "Example", "url": "https://example.com/" + "x" * 2048},
    ],
)
def test_invalid_source_is_rejected(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(data)


@pytest.mark.parametrize("field", ["id", "created_at", "updated_at"])
def test_client_cannot_set_server_fields(field: str) -> None:
    data = {"type": "upload", "name": "Example", field: "2026-01-01T00:00:00Z"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceCreate.model_validate(data)


def test_read_schema_from_model() -> None:
    now = datetime.now(UTC)
    source = Source(
        id=uuid.uuid4(),
        type=SourceType.UPLOAD,
        name="Uploads",
        url=None,
        created_at=now,
        updated_at=now,
    )

    read = SourceRead.model_validate(source)

    assert read.model_dump() == {
        "id": source.id,
        "type": SourceType.UPLOAD,
        "name": "Uploads",
        "url": None,
        "created_at": now,
        "updated_at": now,
    }
