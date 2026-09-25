from signalscope.core.errors import SignalScopeError


class IngestionError(SignalScopeError):
    """An expected ingestion failure. The message is safe to store on a run."""

    default_message = "Ingestion failed."
