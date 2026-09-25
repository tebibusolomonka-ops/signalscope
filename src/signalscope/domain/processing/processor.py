import asyncio
import uuid
from dataclasses import dataclass

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
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.parsing.registry import ParserRegistry
from signalscope.parsing.types import ParsedDocument
from signalscope.storage.blob import BlobStore


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    document: Document
    extraction: DocumentExtraction


class DocumentProcessor:
    """Parses the raw file of a document and saves the text on the document.

    Reading the file, parsing it and splitting the text into chunks happen
    outside any database transaction. The content, the extraction record and
    the chunks are then saved together in one short transaction, so they
    always describe the same parse.
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
                _apply(document, parsed)
                extraction = await self._save_extraction(session, asset, parser_name, parsed)
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
        return ProcessingResult(document=document, extraction=extraction)

    async def _save_extraction(
        self,
        session: AsyncSession,
        asset: DocumentAsset,
        parser_name: str,
        parsed: ParsedDocument,
    ) -> DocumentExtraction:
        repository = DocumentExtractionRepository(session)
        # A document parsed before keeps its one extraction record, updated in place.
        extraction = await repository.get_by_document(asset.document_id)
        if extraction is None:
            extraction = DocumentExtraction(document_id=asset.document_id)
        extraction.asset_id = asset.id
        extraction.parser_name = parser_name
        extraction.content_type = asset.content_type
        extraction.parser_metadata = dict(parsed.metadata)
        extraction.text_length = len(parsed.text)
        extraction.processed_at = self.clock()
        return await repository.add(extraction)


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
