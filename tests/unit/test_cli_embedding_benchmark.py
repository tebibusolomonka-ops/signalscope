import json
from pathlib import Path

import pytest

from signalscope.cli import benchmark_embedding_command, build_parser
from signalscope.core.settings import Settings
from signalscope.embeddings.provider import EmbeddingInputRole


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-e5"
    dimensions = 2

    async def load(self) -> None:
        pass

    async def embed_texts(self, texts: list[str], role: EmbeddingInputRole) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def write_dataset(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "name": "smoke",
                "documents": [{"key": "d1", "text": "one"}],
                "queries": [{"key": "q1", "text": "one", "relevant_documents": ["d1"]}],
            }
        ),
        encoding="utf-8",
    )


def test_embedding_benchmark_arguments() -> None:
    args = build_parser().parse_args(
        ["benchmark-embedding", "dataset.json", "--output", "report.json", "--limit", "3"]
    )

    assert (args.dataset, args.output, args.limit) == (
        Path("dataset.json"),
        Path("report.json"),
        3,
    )


@pytest.mark.anyio
async def test_embedding_benchmark_writes_report_with_fake_provider(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    output = tmp_path / "report.json"
    write_dataset(dataset)

    code = await benchmark_embedding_command(
        dataset,
        output,
        Settings(),
        provider=FakeProvider(),  # type: ignore[arg-type]
    )

    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["model_id"] == "fake-e5"
    assert report["metrics"]["recall"]["1"] == 1.0
    assert len(report["dataset_fingerprint"]) == 64


@pytest.mark.anyio
async def test_embedding_benchmark_rejects_malformed_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "bad.json"
    dataset.write_text("{}", encoding="utf-8")

    code = await benchmark_embedding_command(
        dataset,
        tmp_path / "report.json",
        Settings(),
        provider=FakeProvider(),  # type: ignore[arg-type]
    )

    assert code == 1
    assert not (tmp_path / "report.json").exists()
