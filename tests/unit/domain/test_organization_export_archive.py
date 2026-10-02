import io
import json
import zipfile
from datetime import UTC, datetime
from uuid import UUID

import pytest

from signalscope.domain.organizations.export_archive import OrganizationExportArchiveService
from signalscope.domain.organizations.export_inventory import OrganizationExportInventory
from signalscope.domain.organizations.model import Organization

ORGANIZATION_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


class InventoryService:
    def __init__(self, inventory: OrganizationExportInventory) -> None:
        self.inventory = inventory

    async def build(self, organization_id: UUID) -> OrganizationExportInventory:
        assert organization_id == ORGANIZATION_ID
        return self.inventory


class MemoryBlobs:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.values[key] = data

    async def get(self, key: str) -> bytes:
        return self.values[key]

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.values


def inventory() -> OrganizationExportInventory:
    empty: tuple[()] = ()
    return OrganizationExportInventory(
        organization=(
            Organization(
                id=ORGANIZATION_ID,
                name="Médias du Monde",
                slug="medias-du-monde",
                created_by_user_id=UUID("22222222-2222-2222-2222-222222222222"),
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
        memberships=empty,
        sources=empty,
        documents=empty,
        document_revisions=empty,
        document_chunks=empty,
        document_assets=empty,
        entities=empty,
        entity_mentions=empty,
        claims=empty,
        claim_evidence=empty,
        events=empty,
        event_evidence=empty,
        event_clusters=empty,
        event_cluster_members=empty,
        investigations=empty,
        investigation_items=empty,
        investigation_collaborators=empty,
        research_sessions=empty,
        research_turns=empty,
        security_audit=empty,
        operation_history=empty,
    )


@pytest.mark.anyio
async def test_archive_has_safe_deterministic_utf8_structure() -> None:
    blobs = MemoryBlobs()
    service = OrganizationExportArchiveService(
        InventoryService(inventory()),
        blobs,
        clock=lambda: NOW,  # type: ignore[arg-type]
    )

    first = await service.store(ORGANIZATION_ID, "organization-exports/export.zip")
    second = await service.build(ORGANIZATION_ID)

    assert first.data == second.data
    assert first.sha256 == second.sha256
    assert first.size_bytes == len(first.data)
    assert blobs.values["organization-exports/export.zip"] == first.data
    with zipfile.ZipFile(io.BytesIO(first.data)) as archive:
        assert archive.namelist() == ["manifest.json", "organization.json"]
        manifest = json.loads(archive.read("manifest.json"))
        organization = json.loads(archive.read("organization.json"))
        exported_text = "".join(archive.read(name).decode("utf-8") for name in archive.namelist())
    assert manifest["record_counts"] == {"organization": 1}
    assert manifest["files"] == ["organization.json"]
    assert manifest["archive_sha256"] is None
    assert organization["name"] == "Médias du Monde"
    assert "password" not in exported_text
    assert all(".." not in name and not name.startswith("/") for name in manifest["files"])
