import hashlib
import io
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from signalscope.core.errors import InvalidInputError, ServiceUnavailableError
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.organizations.export_archive import OrganizationExportArchiveService
from signalscope.domain.organizations.export_inventory import OrganizationExportInventory
from signalscope.domain.organizations.model import Organization

ORGANIZATION_ID = UUID("11111111-1111-1111-1111-111111111111")
DOCUMENT_ID = UUID("33333333-3333-3333-3333-333333333333")
ASSET_ID = UUID("44444444-4444-4444-4444-444444444444")
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
    organization_data = (
        json.dumps(organization, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    assert manifest["format_version"] == "2"
    assert manifest["files"] == [
        {
            "path": "organization.json",
            "size_bytes": len(organization_data),
            "sha256": hashlib.sha256(organization_data).hexdigest(),
        }
    ]
    assert organization["name"] == "Médias du Monde"
    assert "password" not in exported_text
    assert all(
        ".." not in file["path"] and not file["path"].startswith("/") for file in manifest["files"]
    )


@pytest.mark.anyio
async def test_archive_checksum_changes_when_member_content_changes() -> None:
    first_inventory = inventory()
    changed_inventory = inventory()
    changed_inventory.organization[0].name = "Changed name"

    first = await OrganizationExportArchiveService(
        InventoryService(first_inventory),
        clock=lambda: NOW,  # type: ignore[arg-type]
    ).build(ORGANIZATION_ID)
    changed = await OrganizationExportArchiveService(
        InventoryService(changed_inventory),
        clock=lambda: NOW,  # type: ignore[arg-type]
    ).build(ORGANIZATION_ID)

    assert first.sha256 == hashlib.sha256(first.data).hexdigest()
    assert changed.sha256 == hashlib.sha256(changed.data).hexdigest()
    assert first.sha256 != changed.sha256
    with zipfile.ZipFile(io.BytesIO(first.data)) as archive:
        assert archive.namelist() == sorted(archive.namelist())


@pytest.mark.anyio
async def test_manifest_describes_binary_assets_without_storage_keys() -> None:
    content = b"binary report"
    asset = DocumentAsset(
        id=ASSET_ID,
        document_id=DOCUMENT_ID,
        storage_key="document-assets/private-key.pdf",
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        created_at=NOW,
        updated_at=NOW,
    )
    exported = replace(inventory(), document_assets=(asset,))

    blobs = MemoryBlobs()
    blobs.values[asset.storage_key] = content
    result = await OrganizationExportArchiveService(
        InventoryService(exported),
        blobs,
        clock=lambda: NOW,  # type: ignore[arg-type]
    ).build(ORGANIZATION_ID)

    assert result.manifest["assets"] == [
        {
            "asset_id": str(ASSET_ID),
            "document_id": str(DOCUMENT_ID),
            "path": f"assets/{ASSET_ID}",
            "filename": "report.pdf",
            "content_type": "application/pdf",
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    ]
    assert "storage_key" not in result.manifest["assets"][0]
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        assert archive.read(f"assets/{ASSET_ID}") == content


@pytest.mark.anyio
async def test_archive_can_omit_binary_assets() -> None:
    content = b"binary report"
    asset = DocumentAsset(
        id=ASSET_ID,
        document_id=DOCUMENT_ID,
        storage_key="document-assets/private-key.pdf",
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        created_at=NOW,
        updated_at=NOW,
    )
    exported = replace(inventory(), document_assets=(asset,))

    result = await OrganizationExportArchiveService(
        InventoryService(exported),
        clock=lambda: NOW,  # type: ignore[arg-type]
    ).build(ORGANIZATION_ID, include_assets=False)

    assert result.manifest["assets"] == []
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        assert f"assets/{ASSET_ID}" not in archive.namelist()


@pytest.mark.anyio
async def test_export_rejects_asset_bytes_that_do_not_match_the_record() -> None:
    asset = DocumentAsset(
        id=ASSET_ID,
        document_id=DOCUMENT_ID,
        storage_key="document-assets/report.pdf",
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        created_at=NOW,
        updated_at=NOW,
    )
    blobs = MemoryBlobs()
    blobs.values[asset.storage_key] = b"wrong"
    service = OrganizationExportArchiveService(
        InventoryService(replace(inventory(), document_assets=(asset,))), blobs
    )

    with pytest.raises(ServiceUnavailableError, match="Stored asset does not match its record"):
        await service.build(ORGANIZATION_ID)


@pytest.mark.anyio
async def test_export_applies_asset_count_and_size_limits_before_reading_blobs() -> None:
    asset = DocumentAsset(
        id=ASSET_ID,
        document_id=DOCUMENT_ID,
        storage_key="document-assets/report.pdf",
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        created_at=NOW,
        updated_at=NOW,
    )
    exported = replace(inventory(), document_assets=(asset,))

    with pytest.raises(InvalidInputError, match="1 assets; the limit is 0"):
        await OrganizationExportArchiveService(
            InventoryService(exported), MemoryBlobs(), max_assets=0
        ).build(ORGANIZATION_ID)
    with pytest.raises(InvalidInputError, match="12 asset bytes; the limit is 11"):
        await OrganizationExportArchiveService(
            InventoryService(exported), MemoryBlobs(), max_bytes=11
        ).build(ORGANIZATION_ID)
