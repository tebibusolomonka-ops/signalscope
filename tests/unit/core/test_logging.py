import logging
import re

import pytest

from signalscope.core.logging import build_formatter, configure_logging
from signalscope.core.settings import LogLevel, Settings

LINE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z INFO     signalscope\.test: hello$"
)


def test_formatter_output() -> None:
    record = logging.makeLogRecord(
        {
            "name": "signalscope.test",
            "levelno": logging.WARNING,
            "levelname": "WARNING",
            "msg": "disk usage at %d%%",
            "args": (91,),
            # 2026-01-02 03:04:05.678 UTC
            "created": 1767323045.678,
            "msecs": 678.0,
        }
    )

    line = build_formatter().format(record)

    assert line == "2026-01-02T03:04:05.678Z WARNING  signalscope.test: disk usage at 91%"


def test_configure_logging_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings())

    logging.getLogger("signalscope.test").info("hello")

    assert LINE_PATTERN.match(capsys.readouterr().err.strip())


def test_configure_logging_uses_level_from_settings(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(log_level=LogLevel.WARNING))
    logger = logging.getLogger("signalscope.test")

    logger.info("skipped")
    logger.warning("kept")

    output = capsys.readouterr().err
    assert "skipped" not in output
    assert "kept" in output


def test_configure_logging_twice_does_not_duplicate_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(Settings())
    configure_logging(Settings())

    logging.getLogger("signalscope.test").info("hello")

    assert len(capsys.readouterr().err.splitlines()) == 1


def test_configure_logging_keeps_other_handlers(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging(Settings())

    logging.getLogger("signalscope.test").info("hello")

    assert caplog.messages == ["hello"]
