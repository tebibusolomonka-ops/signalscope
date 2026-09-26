import io
import sys

import pytest

from fake_embeddings import FakeEmbeddingProvider
from signalscope.cli import build_parser, main, run_embedding_worker
from signalscope.core.settings import Settings
from signalscope.embeddings.registry import EmbeddingProviderRegistry

pytestmark = pytest.mark.anyio

# The .invalid domain never resolves, and these tests fail before connecting.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_arguments() -> None:
    args = build_parser().parse_args(
        ["run-embedding-worker", "--poll-seconds", "2", "--max-jobs", "3", "--batch-size", "8"]
    )

    assert (args.command, args.once, args.poll_seconds, args.max_jobs, args.batch_size) == (
        "run-embedding-worker",
        False,
        2.0,
        3,
        8,
    )


def test_batch_size_defaults_to_the_settings() -> None:
    assert build_parser().parse_args(["run-embedding-worker", "--once"]).batch_size is None


@pytest.mark.parametrize(
    "arguments",
    [["--once", "--max-jobs", "2"], ["--batch-size", "0"], ["--batch-size", "many"]],
    ids=["once with max jobs", "zero batch size", "batch size not a number"],
)
def test_bad_arguments(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["run-embedding-worker", *arguments])

    assert error.value.code == 2


def test_local_embeddings_must_be_enabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED", raising=False)
    monkeypatch.setenv("SIGNALSCOPE_DATABASE_URL", FAKE_DATABASE_URL)

    assert main(["run-embedding-worker", "--once"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "Error: Local embeddings are not enabled. Set SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED=true.\n"
    )


async def test_missing_local_embedding_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules makes the library look not installed.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    out, err = io.StringIO(), io.StringIO()
    settings = Settings(database_url=FAKE_DATABASE_URL, local_embeddings_enabled=True)

    code = await run_embedding_worker(settings, out, err)

    assert (code, out.getvalue()) == (1, "")
    assert "local-embeddings extra" in err.getvalue()
    assert 'pip install -e ".[local-embeddings]"' in err.getvalue()


async def test_missing_database_url() -> None:
    providers = EmbeddingProviderRegistry()
    providers.register(FakeEmbeddingProvider())
    out, err = io.StringIO(), io.StringIO()

    code = await run_embedding_worker(Settings(), out, err, providers=providers)

    assert code == 1
    assert err.getvalue() == (
        "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.\n"
    )
