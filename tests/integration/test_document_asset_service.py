import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import ConflictError, InvalidInputError, NotFoundError
from signalscope.domain.documents import files
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_repository import DocumentAssetRepository
from signalscope.domain.documents.asset_service import DocumentAssetService
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def blob_root(tmp_path: Path) -> Path:
    return tmp_path / "blobs"


@pytest.fixture
def blobs(blob_root: Path) -> LocalBlobStore:
    return LocalBlobStore(blob_root)


@pytest.fixture
async def document(session_factory: async_sessionmaker[AsyncSession]) -> Document:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Uploads")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title="Report")
        session.add(document)
        await session.commit()
    return document


def stored_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []


async def attach(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    document_id: uuid.UUID,
    data: bytes = b"%PDF-1.4 test",
) -> DocumentAsset:
    async with session_factory() as session:
        return await DocumentAssetService(session, blobs).attach(
            document_id, filename="uploads/report.pdf", content_type="application/pdf", data=data
        )


async def test_attach_stores_bytes_and_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    document: Document,
) -> None:
    asset = await attach(session_factory, blobs, document.id)

    async with session_factory() as session:
        service = DocumentAssetService(session, blobs)
        saved = await service.get(document.id)
        data = await service.read(saved)

    assert saved.id == asset.id
    assert saved.filename == "report.pdf"
    assert saved.content_type == "application/pdf"
    assert saved.size_bytes == len(b"%PDF-1.4 test")
    assert saved.sha256 == hashlib.sha256(b"%PDF-1.4 test").hexdigest()
    assert data == b"%PDF-1.4 test"
    # The key is random, so the file name never reaches the file system.
    assert "report" not in saved.storage_key
    assert [path.read_bytes() for path in stored_files(blob_root)] == [b"%PDF-1.4 test"]


async def test_unknown_document(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, blob_root: Path
) -> None:
    with pytest.raises(NotFoundError, match="Document was not found."):
        await attach(session_factory, blobs, uuid.uuid4())

    assert stored_files(blob_root) == []


async def test_second_asset_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    document: Document,
) -> None:
    await attach(session_factory, blobs, document.id, b"first")

    with pytest.raises(ConflictError, match="Document already has a stored file."):
        await attach(session_factory, blobs, document.id, b"second")

    assert [path.read_bytes() for path in stored_files(blob_root)] == [b"first"]


async def test_oversized_file_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(files, "MAX_FILE_BYTES", 10)

    with pytest.raises(InvalidInputError, match="File is larger than"):
        await attach(session_factory, blobs, document.id, b"x" * 11)

    assert stored_files(blob_root) == []


async def test_database_failure_removes_the_blob(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_add(self: DocumentAssetRepository, asset: DocumentAsset) -> DocumentAsset:
        raise RuntimeError("database is down")

    monkeypatch.setattr(DocumentAssetRepository, "add", broken_add)

    with pytest.raises(RuntimeError, match="database is down"):
        await attach(session_factory, blobs, document.id)

    assert stored_files(blob_root) == []


async def test_asset_saved_at_the_same_time_is_a_conflict(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await attach(session_factory, blobs, document.id, b"first")

    # Act as if the check ran before the other request saved its file.
    async def no_asset_yet(
        self: DocumentAssetRepository, document_id: uuid.UUID
    ) -> DocumentAsset | None:
        return None

    monkeypatch.setattr(DocumentAssetRepository, "get_by_document", no_asset_yet)

    with pytest.raises(ConflictError, match="Document already has a stored file."):
        await attach(session_factory, blobs, document.id, b"second")

    assert [path.read_bytes() for path in stored_files(blob_root)] == [b"first"]


async def test_document_without_a_file(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, document: Document
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Document has no stored file."):
            await DocumentAssetService(session, blobs).get(document.id)
