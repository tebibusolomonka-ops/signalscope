import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import aclosing

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError, SignalScopeError
from signalscope.domain.ingestion.adapter import IngestedItem, IngestionAdapter
from signalscope.domain.ingestion.model import IngestionRun
from signalscope.domain.ingestion.registry import AdapterRegistry
from signalscope.domain.ingestion.repository import IngestionRunRepository
from signalscope.domain.ingestion.retry import RetryPolicy, is_retryable
from signalscope.domain.ingestion.service import IngestionRunService
from signalscope.domain.ingestion.writer import DocumentWriter, WriteOutcome
from signalscope.domain.sources.model import Source
from signalscope.domain.sources.repository import SourceRepository

logger = logging.getLogger(__name__)

UNEXPECTED_ERROR_MESSAGE = "Ingestion failed with an unexpected error."

DEFAULT_RETRY_POLICY = RetryPolicy()

Sleep = Callable[[float], Awaitable[None]]


class IngestionExecutor:
    """Runs one ingestion run from start to finish.

    Every step uses its own short transaction, so no transaction stays open
    while an adapter waits on the network or between attempts.

    A failure that is likely to pass, such as a timeout, is tried again after a
    delay. The run stays running in between. Documents saved by an earlier
    attempt are kept, and the next attempt counts them as duplicates. When the
    error cannot be retried or no attempts are left, the run is marked failed.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: AdapterRegistry,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.retry_policy = retry_policy
        self.sleep = sleep

    async def execute(self, run_id: uuid.UUID) -> IngestionRun:
        """Run a pending ingestion run and return it in its final state.

        Failures during the run are stored on the run, not raised. A run that is
        missing or not pending raises before anything is fetched.
        """
        source = await self._start(run_id)
        try:
            # Choosing the adapter after the run started lets an unsupported
            # source type end as a normal failed run.
            adapter = self.registry.get(source.type)
            await self._fetch_with_retries(run_id, source, adapter)
        except Exception as error:
            logger.exception("Ingestion run %s failed", run_id)
            async with self.session_factory() as session:
                return await IngestionRunService(session).mark_failed(run_id, _safe_message(error))

        async with self.session_factory() as session:
            return await IngestionRunService(session).mark_completed(run_id)

    async def _start(self, run_id: uuid.UUID) -> Source:
        async with self.session_factory() as session:
            run = await IngestionRunService(session).mark_running(run_id)
            source = await SourceRepository(session).get(run.source_id)
            if source is None:
                raise NotFoundError("Source was not found.")
            return source

    async def _fetch_with_retries(
        self, run_id: uuid.UUID, source: Source, adapter: IngestionAdapter
    ) -> None:
        while True:
            async with self.session_factory() as session:
                # A run is executed only once, so its attempt count numbers the attempts.
                attempt = await IngestionRunRepository(session).add_attempt(run_id)
                await session.commit()
            try:
                await self._fetch(run_id, source, adapter)
                return
            except Exception as error:
                if not (is_retryable(error) and self.retry_policy.allows_retry_after(attempt)):
                    raise
                delay = self.retry_policy.delay_after(attempt)
                logger.warning(
                    "Ingestion run %s attempt %s failed (%s). Trying again in %s seconds.",
                    run_id,
                    attempt,
                    error,
                    delay,
                )
            await self.sleep(delay)

    async def _fetch(self, run_id: uuid.UUID, source: Source, adapter: IngestionAdapter) -> None:
        # aclosing lets the adapter clean up right away when saving an item fails.
        async with aclosing(adapter.fetch(source)) as items:
            async for item in items:
                await self._save(run_id, source, item)

    async def _save(self, run_id: uuid.UUID, source: Source, item: IngestedItem) -> None:
        async with self.session_factory() as session:
            result = await DocumentWriter(session).write(source.id, item)
            created = result.outcome is WriteOutcome.CREATED
            await IngestionRunRepository(session).add_counts(
                run_id,
                items_seen=1,
                documents_created=1 if created else 0,
                duplicates_skipped=0 if created else 1,
            )
            await session.commit()


def _safe_message(error: Exception) -> str:
    # SignalScope errors carry messages written for people. Other errors can
    # contain internal details, so only the logs get those.
    if isinstance(error, SignalScopeError):
        return str(error)
    return UNEXPECTED_ERROR_MESSAGE
