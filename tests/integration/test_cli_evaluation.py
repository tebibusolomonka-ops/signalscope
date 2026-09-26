import io
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from fake_reranker import FakeReranker
from signalscope.cli import evaluate_retrieval
from signalscope.core.settings import Settings
from signalscope.domain.documents.model import Document

pytestmark = pytest.mark.anyio

EXAMPLE = Path(__file__).parents[2] / "docs" / "examples" / "media-smoke.json"


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    return Settings(database_url=migrated_database.database_url)


async def run(settings: Settings, mode: str, ks: list[int]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await evaluate_retrieval(
        EXAMPLE, settings, out, err, mode=mode, ks=ks, provider=FakeEmbeddingProvider()
    )
    return code, out.getvalue(), err.getvalue()


def section(output: str, title: str) -> list[str]:
    lines = output.splitlines()
    start = lines.index(title) + 1
    end = lines.index("", start) if "" in lines[start:] else len(lines)
    return lines[start:end]


async def test_lexical_mode(settings: Settings) -> None:
    out, err = io.StringIO(), io.StringIO()

    # Lexical mode needs no model at all.
    code = await evaluate_retrieval(EXAMPLE, settings, out, err, mode="lexical", ks=[1, 5])

    assert (code, err.getvalue()) == (0, "")
    output = out.getvalue()
    assert output.startswith("Dataset: media-smoke\nQueries: 4\n\nLexical\n")
    names = [line.split(":")[0] for line in section(output, "Lexical")]
    assert names == [
        "Recall@1",
        "Recall@5",
        "MRR@1",
        "MRR@5",
        "nDCG@1",
        "nDCG@5",
        "Mean",
        "p50",
        "p95",
    ]
    assert "Semantic" not in output


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
async def test_model_modes_with_a_fake_model(settings: Settings, mode: str) -> None:
    code, output, err = await run(settings, mode, [1])

    assert (code, err) == (0, "")
    lines = section(output, mode.capitalize())
    assert re.fullmatch(r"Recall@1: [01]\.\d{3}", lines[0])
    assert re.fullmatch(r"p95: \d+\.\d{2} ms", lines[-1])


async def test_all_modes(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    code, output, _ = await run(settings, "all", [1, 5, 10])

    assert code == 0
    assert [line for line in output.splitlines() if line in ("Lexical", "Semantic", "Hybrid")] == [
        "Lexical",
        "Semantic",
        "Hybrid",
    ]
    assert "MRR@10: " in output
    # Every run rolled its rows back.
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 0


async def test_reranked_mode(settings: Settings) -> None:
    out, err = io.StringIO(), io.StringIO()
    reranker = FakeReranker()

    code = await evaluate_retrieval(
        EXAMPLE,
        settings,
        out,
        err,
        mode="reranked",
        ks=[1, 5],
        provider=FakeEmbeddingProvider(),
        reranker=reranker,
    )

    assert (code, err.getvalue()) == (0, "")
    lines = section(out.getvalue(), "Reranked")
    assert [line.split(":")[0] for line in lines][-3:] == [
        "Reranking mean",
        "Reranking p50",
        "Reranking p95",
    ]
    # One reranker call per query.
    assert len(reranker.calls) == 4


async def test_all_modes_include_the_reranker_when_it_is_there(settings: Settings) -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await evaluate_retrieval(
        EXAMPLE,
        settings,
        out,
        err,
        ks=[1],
        provider=FakeEmbeddingProvider(),
        reranker=FakeReranker(),
    )

    assert code == 0
    titles = [line for line in out.getvalue().splitlines() if line.istitle() and ":" not in line]
    assert titles == ["Lexical", "Semantic", "Hybrid", "Reranked"]


async def test_all_modes_say_when_the_reranker_is_missing(settings: Settings) -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await evaluate_retrieval(
        EXAMPLE, settings, out, err, ks=[1], provider=FakeEmbeddingProvider()
    )

    assert (code, err.getvalue()) == (0, "")
    assert out.getvalue().endswith(
        "\nReranked\n"
        "Skipped: Local reranking is not enabled. Set SIGNALSCOPE_LOCAL_RERANKING_ENABLED=true.\n"
    )


async def test_json_report_next_to_the_text_output(settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    out, err = io.StringIO(), io.StringIO()

    code = await evaluate_retrieval(
        EXAMPLE,
        settings,
        out,
        err,
        mode="hybrid",
        ks=[1, 5],
        provider=FakeEmbeddingProvider(),
        json_output=path,
    )

    assert (code, err.getvalue()) == (0, "")
    assert out.getvalue().startswith("Dataset: media-smoke\nQueries: 4\n\nHybrid\n")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert (data["dataset"], data["query_count"], data["ks"]) == ("media-smoke", 4, [1, 5])
    assert list(data["modes"]) == ["hybrid"]
    assert data["models"]["embedding"] == {"provider": "test", "model": "words-4", "dimensions": 4}
    assert data["models"]["reranker"] is None
    assert [query["key"] for query in data["modes"]["hybrid"]["queries"]] == [
        "q1",
        "q2",
        "q3",
        "q4",
    ]
    # Scores and keys only: no document text.
    assert "Offshore wind farms" not in path.read_text(encoding="utf-8")


async def test_json_report_that_cannot_be_written(settings: Settings, tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await evaluate_retrieval(
        EXAMPLE, settings, out, err, mode="lexical", json_output=tmp_path / "missing" / "r.json"
    )

    assert code == 1
    assert err.getvalue().startswith("Error: Cannot write ")


async def run_with_gates(settings: Settings, tmp_path: Path, minimum: float) -> tuple[int, str]:
    path = tmp_path / "gates.json"
    path.write_text(json.dumps({"lexical": {"recall@10": minimum}}), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = await evaluate_retrieval(EXAMPLE, settings, out, err, mode="lexical", quality_gates=path)
    assert err.getvalue() == ""
    return code, out.getvalue()


async def test_quality_gates_that_pass(settings: Settings, tmp_path: Path) -> None:
    code, output = await run_with_gates(settings, tmp_path, 0.0)

    assert code == 0
    assert output.endswith("minimum 0.000, passed\nGates missed: 0 of 1\n")


async def test_quality_gates_that_are_missed(settings: Settings, tmp_path: Path) -> None:
    # The example cannot reach a perfect score with full text search alone.
    code, output = await run_with_gates(settings, tmp_path, 1.0)

    assert code == 1
    assert output.endswith("minimum 1.000, missed\nGates missed: 1 of 1\n")
    # The scores are printed before the gates, as without gates.
    assert "\nLexical\nRecall@1: " in output
