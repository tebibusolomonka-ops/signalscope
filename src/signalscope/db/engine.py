from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from signalscope.core.settings import Settings, SettingsError


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Create the async engine. It opens no connection until it is first used."""
    if settings.database_url is None:
        raise SettingsError("Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.")
    # Check pooled connections before use, so ones closed by the server get replaced.
    return create_async_engine(settings.database_url, pool_pre_ping=True)
