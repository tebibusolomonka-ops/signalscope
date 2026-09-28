"""Local structured extraction with the GLiNER2 library.

The library, and PyTorch with it, is an optional extra. It is only imported
when the model is first used, so SignalScope runs without it.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from signalscope.core.errors import ServiceUnavailableError

GLINER2_PROVIDER = "gliner2"
GLINER2_MODEL = "fastino/gliner2.5-multi-v1"
DEFAULT_DEVICE = "cpu"

# Record name to field specs, such as {"event": ["title::str::What happened"]}.
StructuredSchema = Mapping[str, Sequence[str]]


class StructuredExtractionUnavailableError(ServiceUnavailableError):
    default_message = "Structured extraction model is not available."


class LocalStructuredNotInstalledError(StructuredExtractionUnavailableError):
    default_message = (
        "Local structured extraction needs the local-structured extra. "
        'Install it with: pip install -e ".[local-structured]"'
    )


class InvalidStructuredOutputError(StructuredExtractionUnavailableError):
    default_message = "Structured extraction model returned output that is not an object."


class StructuredExtractor(Protocol):
    """The part of the GLiNER2 model that SignalScope uses."""

    def extract_json(self, text: str, schema: dict[str, list[str]]) -> Any: ...


# Loads a model from its name, a device and an optional cache folder.
ModelLoader = Callable[[str, str, Path | None], StructuredExtractor]


def load_gliner2(model: str, device: str, cache_dir: Path | None) -> StructuredExtractor:
    """Load a model, downloading it into the cache on first use.

    In gliner2 2.0, AutoExtractor.from_pretrained uses cache_dir only for the
    config file, not for the weights. So with a cache folder, the whole model
    is downloaded there first with huggingface_hub, which gliner2 depends on,
    and then loaded from that local folder.
    """
    try:
        from gliner2 import AutoExtractor
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise LocalStructuredNotInstalledError() from error
    source = model if cache_dir is None else snapshot_download(model, cache_dir=str(cache_dir))
    extractor: StructuredExtractor = AutoExtractor.from_pretrained(source, map_location=device)
    return extractor


class StructuredBackend(Protocol):
    """What the event and claim providers need from a structured extraction model."""

    provider_name: str
    model_name: str

    async def extract_json(self, text: str, schema: StructuredSchema) -> dict[str, Any]: ...


def field_text(record: Mapping[str, Any], name: str) -> str | None:
    """Return a field of one extracted record as trimmed text, or None.

    GLiNER2 gives a field as plain text, or as an object with the text when
    it is asked for spans or scores. Anything else, such as a list, counts as
    missing.
    """
    value = record.get(name)
    if isinstance(value, Mapping):
        value = value.get("text")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


class Gliner2StructuredBackend:
    """fastino/gliner2.5-multi-v1, run locally. The event and claim providers share it.

    The model is loaded on first use, and runs in a worker thread, because it
    is slow and would block the event loop. Only extract_json is exposed, so
    the rest of SignalScope never works with the library objects directly.
    """

    provider_name = GLINER2_PROVIDER
    model_name = GLINER2_MODEL

    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        cache_dir: Path | None = None,
        loader: ModelLoader = load_gliner2,
    ) -> None:
        self.device = device
        self.cache_dir = cache_dir
        self.loader = loader
        self._extractor: StructuredExtractor | None = None
        self._load_lock = asyncio.Lock()

    async def extract_json(self, text: str, schema: StructuredSchema) -> dict[str, Any]:
        """Return the records the model found, keyed by record name."""
        extractor = await self._load()
        request = {name: list(fields) for name, fields in schema.items()}
        output = await asyncio.to_thread(extractor.extract_json, text, request)
        if not isinstance(output, Mapping):
            raise InvalidStructuredOutputError()
        return dict(output)

    async def _load(self) -> StructuredExtractor:
        # The lock stops two first calls at the same time from loading the model twice.
        async with self._load_lock:
            if self._extractor is None:
                self._extractor = await asyncio.to_thread(
                    self.loader, self.model_name, self.device, self.cache_dir
                )
        return self._extractor
