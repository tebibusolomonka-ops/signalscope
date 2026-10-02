import hashlib
import io
import json
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import DeclarativeBase

from signalscope.domain.organizations.export_inventory import (
    OrganizationExportInventory,
    OrganizationExportInventoryService,
)
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.storage.blob import BlobStore

EXPORT_FORMAT_VERSION = "1"
MANIFEST_FILE = "manifest.json"
FILES = {
    "organization": "organization.json",
    "memberships": "memberships.jsonl",
    "sources": "sources.jsonl",
    "documents": "documents.jsonl",
    "document_revisions": "document_revisions.jsonl",
    "document_chunks": "document_chunks.jsonl",
    "document_assets": "document_assets.jsonl",
    "entities": "entities.jsonl",
    "entity_mentions": "entity_mentions.jsonl",
    "claims": "claims.jsonl",
    "claim_evidence": "claim_evidence.jsonl",
    "events": "events.jsonl",
    "event_evidence": "event_evidence.jsonl",
    "event_clusters": "event_clusters.jsonl",
    "event_cluster_members": "event_cluster_members.jsonl",
    "investigations": "investigations.jsonl",
    "investigation_items": "investigation_items.jsonl",
    "investigation_collaborators": "investigation_collaborators.jsonl",
    "research_sessions": "research_sessions.jsonl",
    "research_turns": "research_turns.jsonl",
    "security_audit": "security_audit.jsonl",
    "operation_history": "operation_history.jsonl",
}
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class OrganizationExportArchive:
    data: bytes
    sha256: str
    size_bytes: int
    manifest: dict[str, Any]


class OrganizationExportArchiveService:
    """Build and store a portable ZIP from a tenant-scoped inventory."""

    def __init__(
        self,
        inventory: OrganizationExportInventoryService,
        blobs: BlobStore,
        clock: Clock = utc_now,
    ) -> None:
        self.inventory = inventory
        self.blobs = blobs
        self.clock = clock

    async def build(self, organization_id: uuid.UUID) -> OrganizationExportArchive:
        inventory = await self.inventory.build(organization_id)
        files = self._files(inventory)
        manifest: dict[str, Any] = {
            "format_version": EXPORT_FORMAT_VERSION,
            "organization_id": str(organization_id),
            "created_at": self.clock().isoformat(),
            "record_counts": {
                name: inventory.counts[name] for name in FILES if inventory.counts[name]
            },
            "files": list(files),
            "archive_sha256": None,
        }
        archive_data = self._zip(manifest, files)
        return OrganizationExportArchive(
            data=archive_data,
            sha256=hashlib.sha256(archive_data).hexdigest(),
            size_bytes=len(archive_data),
            manifest=manifest,
        )

    async def store(
        self, organization_id: uuid.UUID, artifact_key: str
    ) -> OrganizationExportArchive:
        archive = await self.build(organization_id)
        await self.blobs.put(artifact_key, archive.data)
        return archive

    def _files(self, inventory: OrganizationExportInventory) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        for name, path in FILES.items():
            rows = getattr(inventory, name)
            if not rows:
                continue
            records = [_record(row) for row in rows]
            if name == "organization":
                content = _json(records[0]) + "\n"
            else:
                content = "".join(_json(record) + "\n" for record in records)
            files[path] = content.encode("utf-8")
        return files

    def _zip(self, manifest: dict[str, Any], files: dict[str, bytes]) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            _write(archive, MANIFEST_FILE, (_json(manifest) + "\n").encode("utf-8"))
            for path, content in files.items():
                _write(archive, path, content)
        return output.getvalue()


def _record(row: DeclarativeBase) -> dict[str, Any]:
    mapper = inspect(type(row))
    return {attribute.key: _value(getattr(row, attribute.key)) for attribute in mapper.column_attrs}


def _value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (uuid.UUID, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _write(archive: zipfile.ZipFile, path: str, content: bytes) -> None:
    info = zipfile.ZipInfo(path, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)
