import uuid

import pytest

from signalscope.cli import build_parser, build_registry, main
from signalscope.domain.ingestion.registry import UnsupportedSourceTypeError
from signalscope.domain.sources.model import SourceType
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.rss import RssIngestionAdapter
from signalscope.ingestion.web import WebIngestionAdapter


def test_bad_source_id_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["ingest-source", "not-a-uuid"])

    assert exit_info.value.code == 2
    assert "invalid UUID value: 'not-a-uuid'" in capsys.readouterr().err


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])

    assert exit_info.value.code == 2
    assert "required" in capsys.readouterr().err


def test_missing_database_url_is_an_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_DATABASE_URL", raising=False)

    assert main(["ingest-source", str(uuid.uuid4())]) == 1
    assert capsys.readouterr().err == (
        "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.\n"
    )


def test_invalid_settings_are_an_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SIGNALSCOPE_LOG_LEVEL", "LOUD")

    assert main(["ingest-source", str(uuid.uuid4())]) == 1
    assert "SIGNALSCOPE_LOG_LEVEL must be one of" in capsys.readouterr().err


@pytest.mark.anyio
async def test_default_registry_has_the_fetching_adapters() -> None:
    async with HttpFetcher() as fetcher:
        registry = build_registry(fetcher)

        assert isinstance(registry.get(SourceType.RSS), RssIngestionAdapter)
        assert isinstance(registry.get(SourceType.WEB), WebIngestionAdapter)
        for source_type in [SourceType.UPLOAD, SourceType.API]:
            with pytest.raises(UnsupportedSourceTypeError):
                registry.get(source_type)


def test_schedule_limit_has_a_default() -> None:
    args = build_parser().parse_args(["schedule-ingestion"])

    assert args.command == "schedule-ingestion"
    assert args.limit == 100


def test_schedule_limit_can_be_set() -> None:
    assert build_parser().parse_args(["schedule-ingestion", "--limit", "4"]).limit == 4


@pytest.mark.parametrize(
    ("value", "message"),
    [("0", "must be at least 1: 0"), ("-3", "must be at least 1: -3"), ("many", "whole number")],
)
def test_bad_schedule_limit_is_rejected(
    value: str, message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["schedule-ingestion", "--limit", value])

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["schedule-ingestion"], ["run-worker", "--once"]])
def test_queue_commands_need_a_database(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_DATABASE_URL", raising=False)

    assert main(argv) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.\n"
