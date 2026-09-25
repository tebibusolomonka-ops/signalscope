import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError, SignalScopeError
from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.model import IngestionRun
from signalscope.domain.ingestion.registry import AdapterRegistry
from signalscope.domain.ingestion.repository import IngestionRunRepository
from signalscope.domain.ingestion.service import IngestionRunService
from signalscope.domain.ingestion.writer import DocumentWriter, WriteOutcome
from signalscope.domain.sources.model import Source
from signalscope.domain.sources.repository import SourceRepository

logger = logging.getLogger(__name__)

UNEXPECTED_ERROR_MESSAGE = "Ingestion failed with an unexpected error."


class IngestionExecutor:
    """Runs one ingestion run from start to finish.

    Every step uses its own short transaction, so no transaction stays open
    while an adapter waits on the network. When something fails, the run is
    marked failed and the documents saved before that are kept.
    """

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], registry: AdapterRegistry
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry

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
            async for item in adapter.fetch(source):
                await self._save(run_id, source, item)
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
