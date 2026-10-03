import importlib.metadata
import json
from types import SimpleNamespace

from signalscope.evaluation.model_environment import model_environment_report


def test_reports_present_dependencies_and_cuda() -> None:
    versions = {
        "torch": "2.8.0",
        "transformers": "4.55.0",
        "sentence-transformers": "5.1.0",
        "gliner": "0.2.29",
        "gliner2": "2.0.0",
    }
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True, get_device_name=lambda index: "Test GPU")
    )

    report = model_environment_report(versions.__getitem__, lambda name: torch)  # type: ignore[arg-type]

    assert report.dependencies == {
        "torch": "2.8.0",
        "transformers": "4.55.0",
        "sentence_transformers": "5.1.0",
        "gliner": "0.2.29",
        "gliner2": "2.0.0",
    }
    assert report.cuda_available is True
    assert report.cuda_device == "Test GPU"
    assert report.models["embedding"] == "intfloat/multilingual-e5-small"


def test_reports_absent_dependencies() -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    report = model_environment_report(missing)

    assert all(version is None for version in report.dependencies.values())
    assert report.cuda_available is False
    assert report.cuda_device is None


def test_report_is_json_serializable_and_contains_no_environment_secrets() -> None:
    report = model_environment_report(lambda name: "1.0")

    encoded = json.dumps(report.to_dict())

    assert json.loads(encoded)["models"]["qwen"] == "Qwen/Qwen3-4B-Instruct-2507"
    assert "token" not in encoded.lower()
    assert "password" not in encoded.lower()
