import dataclasses
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from password_helpers import fast_hasher
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.api.routes import documents as document_routes
from signalscope.core.settings import Settings
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.files import MAX_FILE_BYTES
from signalscope.domain.processing.model import DocumentProcessingJob
from signalscope.domain.sources.model import Source, SourceType
from tenancy_helpers import Tenants, add_source, make_tenants

pytestmark = pytest.mark.anyio

TEXT = b"Harbour flood notes."
PLAIN = {"Content-Type": "text/plain; charset=utf-8"}


async def app_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    app.state.password_hasher = fast_hasher()
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
async def files_client(
    database_engine: AsyncEngine, migrated_database: Settings, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Authentication on, with file storage."""
    settings = dataclasses.replace(
        migrated_database, auth_enabled=True, blob_dir=tmp_path / "blobs"
    )
    async for client in app_client(settings):
        yield client


@pytest.fixture
async def open_files_client(
    database_engine: AsyncEngine, migrated_database: Settings, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Authentication off, with file storage."""
    settings = dataclasses.replace(migrated_database, blob_dir=tmp_path / "blobs")
    async for client in app_client(settings):
        yield client


async def upload_source(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID | None
) -> uuid.UUID:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files", organization_id=organization_id)
        session.add(source)
        await session.commit()
        return source.id


def upload_path(source_id: uuid.UUID, organization_id: uuid.UUID | None = None) -> str:
    path = f"/documents/files?source_id={source_id}&filename=notes/harbour-notes.txt"
    return path if organization_id is None else f"{path}&organization_id={organization_id}"


async def test_upload_stores_a_document_and_queues_it(
    files_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(files_client, session_factory)
    a, b = tenants.a, tenants.b
    uploads = await upload_source(session_factory, a.id)

    response = await files_client.post(
        upload_path(uploads, a.id), content=TEXT, headers={**PLAIN, **a.headers["member"]}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "harbour-notes.txt"
    assert body["content_type"] == "text/plain; charset=utf-8"
    assert body["size_bytes"] == len(TEXT)
    assert body["document"]["title"] == "harbour-notes"
    assert body["document"]["source_id"] == str(uploads)
    async with session_factory() as session:
        asset = await session.scalar(select(DocumentAsset))
        job = await session.scalar(select(DocumentProcessingJob))
    assert asset is not None and job is not None
    assert str(job.id) == body["processing_job_id"]
    assert str(asset.document_id) == body["document"]["id"]
    document = f"/documents/{body['document']['id']}"
    assert (await files_client.get(document, headers=a.headers["viewer"])).status_code == 200
    assert (await files_client.get(document, headers=b.headers["owner"])).status_code == 404


async def test_upload_permissions_and_organizations(
    files_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(files_client, session_factory)
    a, b = tenants.a, tenants.b
    uploads = await upload_source(session_factory, a.id)

    async def post(path: str, headers: dict[str, str]) -> httpx.Response:
        return await files_client.post(path, content=TEXT, headers={**PLAIN, **headers})

    viewer = await post(upload_path(uploads, a.id), a.headers["viewer"])
    other = await post(upload_path(uploads, b.id), b.headers["owner"])
    wrong_organization = await post(upload_path(uploads, b.id), tenants.system)
    anonymous = await post(upload_path(uploads, a.id), {})

    assert viewer.status_code == 403
    assert other.status_code == 404
    assert wrong_organization.status_code == 422
    assert wrong_organization.json()["error"]["message"] == (
        "The source does not belong to that organization."
    )
    assert anonymous.status_code == 401
    async with session_factory() as session:
        assert (await session.scalars(select(DocumentAsset))).all() == []


async def test_upload_refuses_bad_files(
    files_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenants: Tenants = await make_tenants(files_client, session_factory)
    a = tenants.a
    uploads = await upload_source(session_factory, a.id)
    feed = await add_source(session_factory, a.id)
    owner = a.headers["owner"]

    unsupported = await files_client.post(
        upload_path(uploads, a.id), content=TEXT, headers={"Content-Type": "image/png", **owner}
    )
    empty = await files_client.post(
        upload_path(uploads, a.id), content=b"", headers={**PLAIN, **owner}
    )
    monkeypatch.setattr(document_routes, "MAX_FILE_BYTES", len(TEXT) - 1)
    too_large = await files_client.post(
        upload_path(uploads, a.id), content=TEXT, headers={**PLAIN, **owner}
    )
    monkeypatch.undo()
    not_upload = await files_client.post(
        upload_path(feed, a.id), content=TEXT, headers={**PLAIN, **owner}
    )

    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["message"] == "No parser is available for image/png."
    assert empty.status_code == 422
    assert too_large.status_code == 422
    assert not_upload.status_code == 409
    async with session_factory() as session:
        assert (await session.scalars(select(DocumentAsset))).all() == []


async def test_upload_without_authentication(
    open_files_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    uploads = await upload_source(session_factory, None)

    response = await open_files_client.post(upload_path(uploads), content=TEXT, headers=PLAIN)

    assert response.status_code == 201


async def test_upload_needs_file_storage(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    uploads = await upload_source(session_factory, tenants.a.id)

    response = await auth_client.post(
        upload_path(uploads, tenants.a.id),
        content=TEXT,
        headers={**PLAIN, **tenants.a.headers["owner"]},
    )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "File storage is not configured."


async def test_upload_limits(open_files_client: httpx.AsyncClient) -> None:
    response = await open_files_client.get("/documents/files/limits")

    assert response.status_code == 200
    assert response.json() == {
        "content_types": [
            "application/json",
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/xhtml+xml",
            "text/html",
            "text/plain",
        ],
        "max_bytes": MAX_FILE_BYTES,
    }
