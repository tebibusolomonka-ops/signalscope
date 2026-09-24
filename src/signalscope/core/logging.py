import logging
import time

from signalscope.core.settings import Settings

LOG_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
HANDLER_NAME = "signalscope"


def build_formatter() -> logging.Formatter:
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    # UTC so logs from different machines and time zones line up.
    formatter.converter = time.gmtime
    return formatter


def configure_logging(settings: Settings) -> None:
    """Send log records to stderr in one line per record.

    Safe to call more than once. Only the handler added here is replaced, so
    handlers added by other code, such as test tools, stay in place.
    """
    handler = logging.StreamHandler()
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(build_formatter())

    root = logging.getLogger()
    for existing in root.handlers[:]:
        if existing.get_name() == HANDLER_NAME:
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level.value)
