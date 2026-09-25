class SignalScopeError(Exception):
    """Base class for errors that SignalScope raises on purpose.

    The message should be short and safe to show to a user.
    """

    default_message = "Something went wrong."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class NotFoundError(SignalScopeError):
    default_message = "Resource was not found."


class ConflictError(SignalScopeError):
    default_message = "Resource conflicts with existing data."


class ServiceUnavailableError(SignalScopeError):
    default_message = "Service is not available."


class InvalidInputError(SignalScopeError):
    default_message = "Input is not valid."
