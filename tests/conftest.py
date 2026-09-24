import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    # configure_logging changes the root logger, which all tests share.
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
