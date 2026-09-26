import io
import json
import sys
from pathlib import Path

import pytest

from fake_embeddings import FakeEmbeddingProvider
from signalscope.cli import build_parser, check_embedding_model, evaluate_retrieval, main
from signalscope.core.settings import Settings
from signalscope.evaluation.loader import load_dataset
from signalscope.evaluation.metrics import MetricsSummary
from signalscope.evaluation.report import format_reports
from signalscope.evaluation.retrieval import LatencySummary, RetrievalReport

pytestmark = pytest.mark.anyio

# The .invalid domain never resolves, and these tests fail before connecting.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"
EXAMPLE = Path(__file__).parents[2] / "docs" / "examples" / "media-smoke.json"


def test_example_dataset_is_valid() -> None:
    dataset = load_dataset(EXAMPLE)

    assert dataset.name == "media-smoke"
    assert len(dataset.queries) == 4


def test_arguments() -> None:
    args = build_parser().parse_args(
        ["evaluate-retrieval", "data.json", "--mode", "hybrid", "--k", "10,1,5,1"]
    )

    assert (args.command, args.dataset, args.mode, args.k) == (
        "evaluate-retrieval",
        Path("data.json"),
        "hybrid",
        [1, 5, 10],
    )


def test_defaults() -> None:
    args = build_parser().parse_args(["evaluate-retrieval", "data.json"])

    assert (args.mode, args.k) == ("all", [1, 5, 10])


@pytest.mark.parametrize(
    "arguments",
    [["--k", "0"], ["--k", "1,x"], ["--k", "51"], ["--k", ""], ["--mode", "fuzzy"]],
    ids=["zero k", "not a number", "k too large", "empty k", "unknown mode"],
)
def test_bad_arguments(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["evaluate-retrieval", "data.json", *arguments])

    assert error.value.code == 2


async def test_bad_dataset(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"name": "x"}), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()

    code = await evaluate_retrieval(path, Settings(database_url=FAKE_DATABASE_URL), out, err)

    assert (code, out.getvalue()) == (1, "")
    assert (
        err.getvalue()
        == "Error: Dataset " + str(path) + " is missing fields: documents, queries.\n"
    )


async def test_lexical_mode_needs_no_model_but_a_database() -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await evaluate_retrieval(EXAMPLE, Settings(), out, err, mode="lexical")

    assert code == 1
    assert (
        err.getvalue() == "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.\n"
    )


@pytest.mark.parametrize("mode", ["semantic", "hybrid", "all"])
async def test_model_modes_need_local_embeddings(mode: str) -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await evaluate_retrieval(
        EXAMPLE, Settings(database_url=FAKE_DATABASE_URL), out, err, mode=mode
    )

    assert code == 1
    assert "SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED=true" in err.getvalue()


async def test_missing_local_embedding_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    out, err = io.StringIO(), io.StringIO()
    settings = Settings(database_url=FAKE_DATABASE_URL, local_embeddings_enabled=True)

    code = await evaluate_retrieval(EXAMPLE, settings, out, err, mode="semantic")

    assert code == 1
    assert 'pip install -e ".[local-embeddings]"' in err.getvalue()


def test_report_format() -> None:
    report = RetrievalReport(
        mode="lexical",
        dataset="media-smoke",
        ks=(1, 5),
        metrics=MetricsSummary(
            query_count=4,
            recall={1: 0.5, 5: 0.75},
            mrr={1: 0.5, 5: 0.625},
            ndcg={1: 0.5, 5: 0.6789},
        ),
        queries=(),
        latency=LatencySummary(mean_ms=1.234, p50_ms=1.0, p95_ms=2.5),
    )

    assert format_reports("media-smoke", 4, [report]) == (
        "Dataset: media-smoke\n"
        "Queries: 4\n"
        "\n"
        "Lexical\n"
        "Recall@1: 0.500\n"
        "Recall@5: 0.750\n"
        "MRR@1: 0.500\n"
        "MRR@5: 0.625\n"
        "nDCG@1: 0.500\n"
        "nDCG@5: 0.679\n"
        "Mean: 1.23 ms\n"
        "p50: 1.00 ms\n"
        "p95: 2.50 ms\n"
    )


async def test_model_check_with_a_fake_model() -> None:
    out, err = io.StringIO(), io.StringIO()
    provider = FakeEmbeddingProvider()

    code = await check_embedding_model(Settings(), out, err, provider=provider)

    assert (code, err.getvalue()) == (0, "")
    lines = out.getvalue().splitlines()
    assert lines[:4] == [
        "Model: test/words-4",
        "Dimensions: 4",
        "Query vector: 4 numbers",
        "Passage vector: 4 numbers",
    ]
    assert lines[4].startswith("Cosine similarity: ")
    assert provider.calls == [
        ["offshore wind energy"],
        ["Offshore wind farms produced more electricity this year."],
    ]


async def test_model_check_needs_local_embeddings() -> None:
    out, err = io.StringIO(), io.StringIO()

    assert await check_embedding_model(Settings(), out, err) == 1
    assert "SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED" in err.getvalue()


async def test_model_check_reports_a_model_error() -> None:
    out, err = io.StringIO(), io.StringIO()
    provider = FakeEmbeddingProvider()
    provider.answer = [[1.0]]

    assert await check_embedding_model(Settings(), out, err, provider=provider) == 1
    assert "1 dimensions instead of 4" in err.getvalue()
