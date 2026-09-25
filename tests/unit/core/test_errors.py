import pytest

from signalscope.core.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    SignalScopeError,
    short_error_message,
)
from signalscope.core.settings import SettingsError


@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (SignalScopeError, "Something went wrong."),
        (NotFoundError, "Resource was not found."),
        (ConflictError, "Resource conflicts with existing data."),
        (InvalidInputError, "Input is not valid."),
    ],
)
def test_error_uses_default_message(error_type: type[SignalScopeError], message: str) -> None:
    assert str(error_type()) == message


def test_error_uses_given_message() -> None:
    assert str(NotFoundError("Source was not found.")) == "Source was not found."


def test_settings_error_is_signalscope_error_and_value_error() -> None:
    error = SettingsError("Database URL is not configured.")

    assert isinstance(error, SignalScopeError)
    assert isinstance(error, ValueError)


def test_short_error_message() -> None:
    assert short_error_message("  Feed went away.  ") == "Feed went away."
    assert short_error_message("   ") == "Something went wrong."

    long_message = short_error_message("x" * 5000)
    assert len(long_message) == 1000
    assert long_message.endswith("...")
