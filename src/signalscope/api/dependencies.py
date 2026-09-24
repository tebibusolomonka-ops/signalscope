from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ServiceUnavailableError
from signalscope.db.session import get_session


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise ServiceUnavailableError("Database is not configured.")
    # aclosing closes the session when the request ends, also when it fails,
    # instead of leaving that to garbage collection.
    async with aclosing(get_session(session_factory)) as sessions:
        async for session in sessions:
            yield session


DatabaseSession = Annotated[AsyncSession, Depends(database_session)]
