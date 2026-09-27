import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings
from signalscope.research.local import Qwen3LocalAnswerGenerator
from signalscope.research.runtime import create_answer_generator_registry

ENABLED = Settings(
    local_answers_enabled=True,
    local_answer_device="cuda",
    local_answer_max_new_tokens=300,
    local_embedding_cache_dir=Path("models"),
)
QWEN = ("transformers", "Qwen/Qwen3-4B-Instruct-2507")


@pytest.fixture(autouse=True)
def no_model_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make importing Transformers fail, so any attempt to load the model shows."""
    monkeypatch.setitem(sys.modules, "transformers", None)


def test_registry_is_empty_when_disabled() -> None:
    assert create_answer_generator_registry(Settings()).keys() == []


def test_qwen_is_registered_when_enabled_without_loading() -> None:
    registry = create_answer_generator_registry(ENABLED)

    assert registry.keys() == [QWEN]
    generator = registry.only()
    assert isinstance(generator, Qwen3LocalAnswerGenerator)
    assert (generator.device, generator.max_new_tokens, generator.cache_dir) == (
        "cuda",
        300,
        Path("models"),
    )
    # Loading would have failed, because the library cannot be imported here.
    assert generator._loaded is None


@pytest.mark.parametrize("settings", [Settings(), ENABLED], ids=["disabled", "enabled"])
def test_app_keeps_the_registry_and_starts_without_the_model(settings: Settings) -> None:
    app = create_app(settings)

    assert app.state.answer_generators.keys() == ([QWEN] if settings.local_answers_enabled else [])
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_answer_endpoint_is_503_by_default() -> None:
    # The .invalid domain never resolves. The request fails before any query runs.
    settings = Settings(database_url="postgresql+asyncpg://signalscope@db.invalid/signalscope")
    with TestClient(create_app(settings)) as client:
        response = client.post("/research/answer", json={"query": "floods"})

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "No answer model is configured."
