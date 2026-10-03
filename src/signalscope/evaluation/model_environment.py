import importlib
import importlib.metadata
import os
import platform
from collections.abc import Callable
from dataclasses import asdict, dataclass
from types import ModuleType
from typing import Any

from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL
from signalscope.entities.models import GLINER_MULTI
from signalscope.extraction.gliner2 import GLINER2_MODEL
from signalscope.reranking.models import MMARCO_MINILM
from signalscope.research.local import QWEN_MODEL

PackageVersion = Callable[[str], str]
ModuleLoader = Callable[[str], ModuleType]


@dataclass(frozen=True, slots=True)
class ModelEnvironmentReport:
    python_version: str
    platform: str
    cpu_architecture: str
    available_ram_bytes: int | None
    dependencies: dict[str, str | None]
    cuda_available: bool
    cuda_device: str | None
    models: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def model_environment_report(
    package_version: PackageVersion = importlib.metadata.version,
    module_loader: ModuleLoader = importlib.import_module,
) -> ModelEnvironmentReport:
    """Inspect local model dependencies without loading or downloading models."""
    dependencies = {
        name: _version(distribution, package_version)
        for name, distribution in (
            ("torch", "torch"),
            ("transformers", "transformers"),
            ("sentence_transformers", "sentence-transformers"),
            ("gliner", "gliner"),
            ("gliner2", "gliner2"),
        )
    }
    cuda_available = False
    cuda_device = None
    if dependencies["torch"] is not None:
        try:
            torch = module_loader("torch")
            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                cuda_device = str(torch.cuda.get_device_name(0))
        except (ImportError, OSError, RuntimeError):
            pass
    return ModelEnvironmentReport(
        python_version=platform.python_version(),
        platform=platform.platform(),
        cpu_architecture=platform.machine(),
        available_ram_bytes=_available_ram_bytes(),
        dependencies=dependencies,
        cuda_available=cuda_available,
        cuda_device=cuda_device,
        models={
            "embedding": MULTILINGUAL_E5_SMALL.model,
            "reranker": MMARCO_MINILM.model,
            "gliner": GLINER_MULTI.model,
            "gliner2": GLINER2_MODEL,
            "qwen": QWEN_MODEL,
        },
    )


def _version(distribution: str, package_version: PackageVersion) -> str | None:
    try:
        return package_version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _available_ram_bytes() -> int | None:
    if not hasattr(os, "sysconf"):
        return None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
    except (OSError, ValueError):
        return None
    return int(page_size) * int(available_pages)
