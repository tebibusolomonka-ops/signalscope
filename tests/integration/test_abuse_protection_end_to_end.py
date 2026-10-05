import dataclasses
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from password_helpers import fast_hasher
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.users.model import User
from tenancy_helpers import add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio

JSON_LIMIT = 1024
UPLOAD_LIMIT = 1_000_000


@pytest.fixture
async def protected_client(
    database_engine: AsyncEngine,
    migrated_database: Settings,
    tmp_path: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    settings = dataclasses.replace(
        migrated_database,
        auth_enabled=True,
        blob_dir=tmp_path / "blobs",
        max_json_request_bytes=JSON_LIMIT,
        max_upload_request_bytes=UPLOAD_LIMIT,
    )
    app = create_app(settings)
    app.state.password_hasher = fast_hasher()
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def add_upload_source(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as session:
        source = Source(
            type=SourceType.UPLOAD,
            name="Protected uploads",
            organization_id=organization_id,
        )
        session.add(source)
        await session.commit()
        return source.id


async def add_restore_target(
    session_factory: async_sessionmaker[AsyncSession], owner_id: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as session:
        owner = await session.get_one(User, owner_id)
        target = await OrganizationService(session).create(
            owner, "Protected restore target", "protected-restore-target"
        )
        return target.id


async def test_abuse_guards_preserve_normal_tenant_workflows(
    protected_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(protected_client, session_factory)
    a_source = await add_source(session_factory, tenants.a.id, "Tenant A feed")
    b_source = await add_source(session_factory, tenants.b.id, "Tenant B feed")
    await add_document(session_factory, a_source, "A report", ["Harbour alpha evidence."])
    await add_document(session_factory, b_source, "B report", ["Harbour bravo evidence."])
    restore_target_id = await add_restore_target(session_factory, tenants.b.owner_id)

    research = await protected_client.post(
        "/research/context",
        headers=tenants.a.headers["viewer"],
        json={
            "organization_id": str(tenants.a.id),
            "query": "harbour",
            "mode": "lexical",
            "limit": 5,
        },
    )
    assert research.status_code == 200, research.text
    assert [item["title"] for item in research.json()["evidence"]] == ["A report"]
    assert "bravo" not in research.text

    upload_source = await add_upload_source(session_factory, tenants.a.id)
    upload = await protected_client.post(
        (
            "/documents/files"
            f"?source_id={upload_source}&organization_id={tenants.a.id}&filename=notes.txt"
        ),
        headers={"content-type": "text/plain", **tenants.a.headers["member"]},
        content=b"Small tenant upload.",
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["document"]["id"]
    hidden = await protected_client.get(
        f"/documents/{document_id}", headers=tenants.b.headers["owner"]
    )
    assert hidden.status_code == 404

    export = await protected_client.post(
        f"/organizations/{tenants.a.id}/exports",
        headers=tenants.a.headers["owner"],
    )
    assert export.status_code == 201, export.text
    assert export.json()["status"] == "completed"
    archive = await protected_client.get(
        f"/organizations/{tenants.a.id}/exports/{export.json()['id']}/download",
        headers=tenants.a.headers["owner"],
    )
    assert archive.status_code == 200

    backup = await protected_client.post(
        f"/organizations/{tenants.a.id}/backups/run", headers=tenants.system
    )
    assert backup.status_code == 201, backup.text
    assert backup.json()["status"] == "completed"

    plan = await protected_client.post(
        f"/organizations/{restore_target_id}/restore-plan",
        headers={"content-type": "application/zip", **tenants.system},
        content=archive.content,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["conflicts"] == []

    page = await protected_client.get(
        f"/organizations/{tenants.a.id}/exports?limit=100&offset=0",
        headers=tenants.a.headers["owner"],
    )
    invalid_page = await protected_client.get(
        f"/organizations/{tenants.a.id}/exports?limit=101",
        headers=tenants.a.headers["owner"],
    )
    assert page.status_code == 200
    assert invalid_page.status_code == 422

    async with session_factory() as session:
        session.add(
            OrganizationExport(
                organization_id=tenants.a.id,
                requested_by_user_id=tenants.a.owner_id,
                status=OrganizationExportStatus.RUNNING,
                format_version="2",
            )
        )
        await session.commit()
    duplicate = await protected_client.post(
        f"/organizations/{tenants.a.id}/backups/run", headers=tenants.system
    )
    assert duplicate.status_code == 409

    oversized_json = await protected_client.post(
        "/research/context",
        headers=tenants.a.headers["viewer"],
        json={"query": "x" * (JSON_LIMIT * 2)},
    )
    oversized_file = await protected_client.post(
        f"/documents/files?source_id={upload_source}&filename=large.txt",
        headers={"content-type": "text/plain", **tenants.a.headers["member"]},
        content=b"x" * (UPLOAD_LIMIT + 1),
    )
    oversized_archive = await protected_client.post(
        f"/organizations/{restore_target_id}/restore-plan",
        headers={"content-type": "application/zip", **tenants.system},
        content=b"x" * (UPLOAD_LIMIT + 1),
    )
    assert oversized_json.status_code == 413
    assert oversized_file.status_code == 413
    assert oversized_archive.status_code == 413
