from signalscope.core.errors import SignalScopeError


class IngestionError(SignalScopeError):
    """An expected ingestion failure. The message is safe to store on a run."""

    default_message = "Ingestion failed."


class FetchError(IngestionError):
    """Content could not be fetched from a source.

    The fields say why, so retry rules never have to read the message.
    """

    default_message = "Could not fetch the URL."

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int | None = None,
        network_error: bool = False,
    ) -> None:
        super().__init__(message)
        # The HTTP status of the response, when there was one.
        self.status_code = status_code
        # True when no response arrived, such as after a timeout or a refused connection.
        self.network_error = network_error
