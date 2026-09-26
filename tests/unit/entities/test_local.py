"""The GLiNER provider, with a fake in place of the real model.

Nothing here downloads or loads model files.
"""

import asyncio
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from signalscope.entities.local import (
    LocalEntitiesNotInstalledError,
    MultilingualGlinerEntityProvider,
    load_gliner,
)
from signalscope.entities.provider import (
    EntityExtractorUnavailableError,
    InvalidEntityMentionError,
    extract_mentions,
)

pytestmark = pytest.mark.anyio

TEXT = "Angela Merkel visited Siemens in Munich."


class FakeGliner:
    """Returns fixed spans and records how it was called."""

    def __init__(self, spans: list[Any] | None = None) -> None:
        self.spans = spans
        self.calls: list[dict[str, Any]] = []
        self.threads: list[str] = []

    def predict_entities(self, text: str, labels: list[str], **options: Any) -> list[Any]:
        self.calls.append({"text": text, "labels": labels, **options})
        self.threads.append(threading.current_thread().name)
        if self.spans is not None:
            return self.spans
        return [
            {"start": 0, "end": 13, "text": "Angela Merkel", "label": "person", "score": 0.97},
            {"start": 22, "end": 29, "text": "Siemens", "label": "Organization", "score": 0.81},
            {"start": 33, "end": 39, "text": "Munich", "label": "CITY", "score": 0.66},
        ]


class FakeLoader:
    def __init__(self, predictor: FakeGliner) -> None:
        self.predictor = predictor
        self.calls: list[tuple[str, str, Path | None]] = []

    def __call__(self, model: str, device: str, cache_dir: Path | None) -> FakeGliner:
        self.calls.append((model, device, cache_dir))
        return self.predictor


def provider_with(
    predictor: FakeGliner | None = None, **options: Any
) -> tuple[MultilingualGlinerEntityProvider, FakeLoader]:
    loader = FakeLoader(predictor or FakeGliner())
    return MultilingualGlinerEntityProvider(loader=loader, **options), loader


def test_identity_and_defaults() -> None:
    provider, _ = provider_with()

    assert (provider.provider_name, provider.model_name) == ("gliner", "urchade/gliner_multi-v2.1")
    assert (provider.device, provider.threshold, provider.cache_dir) == ("cpu", 0.5, None)
    assert provider.labels == (
        "person",
        "organization",
        "location",
        "country",
        "city",
        "product",
        "event",
        "date",
    )


@pytest.mark.parametrize("threshold", [0, -0.1, 1.5])
def test_bad_threshold(threshold: float) -> None:
    with pytest.raises(ValueError, match="threshold"):
        provider_with(threshold=threshold)


async def test_labels_and_threshold_go_to_the_model() -> None:
    predictor = FakeGliner()
    provider, _ = provider_with(predictor, threshold=0.7)

    await provider.extract(TEXT)

    [call] = predictor.calls
    assert call["text"] == TEXT
    assert call["labels"] == list(provider.labels)
    assert call["threshold"] == 0.7


async def test_spans_become_checked_mentions() -> None:
    provider, _ = provider_with()

    mentions = await extract_mentions(provider, TEXT)

    assert [
        (item.text, item.entity_type, item.start_char, item.end_char, item.confidence)
        for item in mentions
    ] == [
        ("Angela Merkel", "person", 0, 13, 0.97),
        ("Siemens", "organization", 22, 29, 0.81),
        ("Munich", "city", 33, 39, 0.66),
    ]


async def test_model_is_loaded_lazily_once_with_the_device(tmp_path: Path) -> None:
    provider, loader = provider_with(device="cuda", cache_dir=tmp_path)

    assert loader.calls == []
    await asyncio.gather(*(provider.extract(TEXT) for _ in range(4)))
    await provider.extract("Another text.")

    assert loader.calls == [("urchade/gliner_multi-v2.1", "cuda", tmp_path)]


async def test_model_runs_off_the_event_loop_thread() -> None:
    predictor = FakeGliner()
    provider, _ = provider_with(predictor)

    await provider.extract(TEXT)

    assert predictor.threads != [threading.current_thread().name]


@pytest.mark.parametrize(
    ("spans", "message"),
    [
        (["not a span"], "not an object"),
        ([{"start": 0, "end": 6, "label": "person"}], "without text"),
        ([{"start": 0, "end": 6, "text": "Angela", "score": 0.5}], "without label"),
        (
            [{"start": 1, "end": 7, "text": "Angela", "label": "person", "score": 0.5}],
            "not at offsets 1:7",
        ),
        (
            [{"start": 0, "end": 6, "text": "Angela", "label": "person", "score": 3.0}],
            "confidence outside 0 to 1",
        ),
    ],
    ids=["not a span", "no text", "no label", "wrong offsets", "bad score"],
)
async def test_bad_model_output_is_rejected(spans: list[Any], message: str) -> None:
    provider, _ = provider_with(FakeGliner(spans))

    with pytest.raises(InvalidEntityMentionError, match=message):
        await extract_mentions(provider, TEXT)


def test_missing_library_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules makes the import fail, as if the extra were not installed.
    monkeypatch.setitem(sys.modules, "gliner", None)

    with pytest.raises(LocalEntitiesNotInstalledError, match="local-entities") as error:
        load_gliner("urchade/gliner_multi-v2.1", "cpu", None)

    assert isinstance(error.value, EntityExtractorUnavailableError)


async def test_missing_library_surfaces_on_first_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "gliner", None)

    with pytest.raises(LocalEntitiesNotInstalledError):
        await MultilingualGlinerEntityProvider().extract(TEXT)
