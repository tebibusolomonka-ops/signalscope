import io
import re
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import import_file
from signalscope.core.settings import Settings
from signalscope.domain.sources.model import Source, SourceType
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings, tmp_path: Path) -> Settings:
    return Settings(database_url=migrated_database.database_url, blob_dir=tmp_path / "blobs")


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    path = tmp_path / "harbour-notes.txt"
    path.write_text("Harbour flood notes.", encoding="utf-8")
    return path


async def upload_source(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID | None
) -> uuid.UUID:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files", organization_id=organization_id)
        session.add(source)
        await session.commit()
        return source.id


async def run(
    source_id: uuid.UUID, path: Path, settings: Settings, organization_id: uuid.UUID | None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await import_file(
        source_id, path, settings, out=out, err=err, organization_id=organization_id
    )
    return code, out.getvalue(), err.getvalue()


async def test_import_into_an_organization(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    text_file: Path,
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    a_uploads = await upload_source(session_factory, a.id)

    wrong = await run(a_uploads, text_file, settings, b.id)
    code, out, err = await run(a_uploads, text_file, settings, a.id)

    assert wrong[0] == 1
    assert wrong[2] == "Error: The source does not belong to that organization.\n"
    assert (code, err) == (0, "")
    match = re.search(r"Document: ([0-9a-f-]{36})", out)
    assert match is not None
    document = f"/documents/{match[1]}"
    assert (await auth_client.get(document, headers=a.headers["viewer"])).status_code == 200
    assert (await auth_client.get(document, headers=b.headers["owner"])).status_code == 404
    listed = await auth_client.get(f"/documents?{a.query}", headers=a.headers["viewer"])
    assert [item["title"] for item in listed.json()["items"]] == ["harbour-notes"]


async def test_legacy_import_still_works(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings, text_file: Path
) -> None:
    uploads = await upload_source(session_factory, None)

    code, _, err = await run(uploads, text_file, settings, None)
    refused = await run(uploads, text_file, settings, uuid.uuid4())

    assert (code, err) == (0, "")
    assert refused[0] == 1
