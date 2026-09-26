import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.db.errors import is_unique_violation
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_repository import DocumentAssetRepository
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk, chunk_text
from signalscope.domain.documents.extraction import DocumentExtraction
from signalscope.domain.documents.extraction_repository import DocumentExtractionRepository
from signalscope.domain.documents.fingerprint import content_fingerprint
from signalscope.domain.documents.model import LANGUAGE_MAX_LENGTH, Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.documents.revision_repository import DocumentRevisionRepository
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.parsing.registry import ParserRegistry
from signalscope.parsing.types import ParsedDocument
from signalscope.storage.blob import BlobStore


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    document: Document
    extraction: DocumentExtraction
    # The earlier state that this processing replaced, when its content changed.
    revision: DocumentRevision | None = None


@dataclass(frozen=True, slots=True)
class _ProcessedState:
    """What a processed document looked like before it was processed again."""

    title: str | None
    content: str | None
    language: str | None
    url: str | None
    content_hash: str | None
    parser_metadata: dict[str, Any]


class DocumentProcessor:
    """Parses the raw file of a document and saves the text on the document.

    Reading the file, parsing it and splitting the text into chunks happen
    outside any database transaction. The content, the extraction record and
    the chunks are then saved together in one short transaction, so they
    always describe the same parse.

    When a processed document is processed again and its content changes, the
    state it had before is kept as a new revision in that same transaction.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        blobs: BlobStore,
        parsers: ParserRegistry,
        clock: Clock = utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.blobs = blobs
        self.parsers = parsers
        self.clock = clock

    async def process(self, asset_id: uuid.UUID) -> ProcessingResult:
        """Parse one asset. Failures raise errors whose messages are safe to store."""
        asset, document = await self._load(asset_id)
        parser = self.parsers.get(asset.content_type)
        data = await self.blobs.get(asset.storage_key)
        # Parsing can take a while for a big PDF, so it runs off the event loop.
        parsed = await asyncio.to_thread(
            parser.parse,
            data,
            content_type=asset.content_type,
            filename=asset.filename,
            source_url=document.url,
        )
        chunks = await asyncio.to_thread(chunk_text, parsed.text)
        return await self._save(asset, type(parser).__name__, parsed, chunks)

    async def _load(self, asset_id: uuid.UUID) -> tuple[DocumentAsset, Document]:
        async with self.session_factory() as session:
            asset = await DocumentAssetRepository(session).get(asset_id)
            if asset is None:
                raise NotFoundError("Document file was not found.")
            document = await session.get(Document, asset.document_id)
            if document is None:
                raise NotFoundError("Document was not found.")
            return asset, document

    async def _save(
        self,
        asset: DocumentAsset,
        parser_name: str,
        parsed: ParsedDocument,
        chunks: list[TextChunk],
    ) -> ProcessingResult:
        async with self.session_factory() as session:
            try:
                document = await session.get(Document, asset.document_id, with_for_update=True)
                if document is None:
                    raise NotFoundError("Document was not found.")
                extractions = DocumentExtractionRepository(session)
                previous = await extractions.get_by_document(document.id)
                # Only a document that was processed before has a state worth keeping.
                earlier = None if previous is None else _processed_state(document, previous)
                _apply(document, parsed)
                revision = None
                if earlier is not None and earlier.content_hash != document.content_hash:
                    revision = await _save_revision(session, document.id, earlier)
                extraction = await self._save_extraction(
                    extractions, previous, asset, parser_name, parsed
                )
                # The chunk offsets point into the content saved above.
                await DocumentChunkRepository(session).replace_for_document(document.id, chunks)
                # Flush now, so a duplicate content hash shows up as a clear error.
                await session.flush()
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                if is_unique_violation(error):
                    raise ConflictError(
                        "Another document in this source has the same content."
                    ) from error
                raise
            except Exception:
                await session.rollback()
                raise
        return ProcessingResult(document=document, extraction=extraction, revision=revision)

    async def _save_extraction(
        self,
        repository: DocumentExtractionRepository,
        extraction: DocumentExtraction | None,
        asset: DocumentAsset,
        parser_name: str,
        parsed: ParsedDocument,
    ) -> DocumentExtraction:
        # A document parsed before keeps its one extraction record, updated in place.
        if extraction is None:
            extraction = DocumentExtraction(document_id=asset.document_id)
        extraction.asset_id = asset.id
        extraction.parser_name = parser_name
        extraction.content_type = asset.content_type
        extraction.parser_metadata = dict(parsed.metadata)
        extraction.text_length = len(parsed.text)
        extraction.processed_at = self.clock()
        return await repository.add(extraction)


def _processed_state(document: Document, extraction: DocumentExtraction) -> _ProcessedState:
    return _ProcessedState(
        title=document.title,
        content=document.content,
        language=document.language,
        url=document.url,
        content_hash=document.content_hash,
        parser_metadata=dict(extraction.parser_metadata),
    )


async def _save_revision(
    session: AsyncSession, document_id: uuid.UUID, state: _ProcessedState
) -> DocumentRevision:
    repository = DocumentRevisionRepository(session)
    # The document row is locked, so no other processing can take this version.
    version = await repository.latest_version(document_id) + 1
    return await repository.add_snapshot(
        document_id,
        version=version,
        title=state.title,
        content=state.content,
        language=state.language,
        url=state.url,
        content_hash=state.content_hash,
        parser_metadata=state.parser_metadata,
    )


def _apply(document: Document, parsed: ParsedDocument) -> None:
    # Empty text is saved as it is. It means the file had no readable text.
    document.content = parsed.text
    # A title or language that is already set came from a person or the source,
    # so the parser only fills in what is missing.
    if not (document.title or "").strip():
        document.title = parsed.title
    language = parsed.language
    if not document.language and language is not None and len(language) <= LANGUAGE_MAX_LENGTH:
        document.language = language
    document.content_hash = content_fingerprint(
        title=document.title, content=document.content, url=document.url
    )
