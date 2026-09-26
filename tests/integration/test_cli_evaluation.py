import io
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
