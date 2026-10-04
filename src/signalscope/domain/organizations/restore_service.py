import hashlib
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import DeclarativeBase

from signalscope.core.errors import (
    InvalidInputError,
    ServiceUnavailableError,
    SignalScopeError,
    short_error_message,
)
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.investigations.collaborator import InvestigationCollaborator
from signalscope.domain.investigations.item import InvestigationItem
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.operations.attempt import OperationAttempt
from signalscope.domain.organizations.archive_reader import (
    OrganizationArchive,
    OrganizationArchiveReader,
)
from signalscope.domain.organizations.membership import OrganizationMembership
from signalscope.domain.organizations.restore_conflicts import OrganizationRestoreConflictService
from signalscope.domain.organizations.restore_inventory import OrganizationRestoreInventoryService
from signalscope.domain.organizations.restore_record import (
    OrganizationRestore,
    OrganizationRestoreStatus,
)
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.research.turn import ResearchTurn
from signalscope.domain.sources.model import Source
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.model import User
from signalscope.storage.blob import BlobStore

MAX_RESTORE_RECORDS = 100_000


class OrganizationRestoreService:
    """Restore a verified archive into an existing empty organization."""

    def __init__(
        self,
        session: AsyncSession,
        blobs: BlobStore,
        *,
        clock: Clock = utc_now,
        max_records: int = MAX_RESTORE_RECORDS,
    ) -> None:
        self.session = session
        self.blobs = blobs
        self.clock = clock
        self.max_records = max_records

    async def restore(
        self,
        data: bytes,
        target_organization_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        user_mappings: Mapping[str, uuid.UUID] | None = None,
    ) -> OrganizationRestore:
        archive = OrganizationArchiveReader().read(data)
        inventory = OrganizationRestoreInventoryService().build(archive)
        record_count = sum(inventory.counts.values())
        if record_count > self.max_records:
            raise InvalidInputError(
                f"Organization restore has {record_count} records; the limit is {self.max_records}."
            )
        conflicts = await OrganizationRestoreConflictService(self.session).analyze(
            archive, target_organization_id
        )
        if conflicts.conflicts:
            raise InvalidInputError("Restore cannot start: " + "; ".join(conflicts.conflicts))
        users = await self._resolve_users(archive, user_mappings or {})
        self._require_asset_content(archive)

        now = self.clock()
        restore = OrganizationRestore(
            target_organization_id=target_organization_id,
            requested_by_user_id=requested_by_user_id,
            source_export_sha256=hashlib.sha256(data).hexdigest(),
            status=OrganizationRestoreStatus.RUNNING,
            started_at=now,
            summary={"planned": inventory.counts},
        )
        self.session.add(restore)
        await self.session.commit()

        staged_keys: list[str] = []
        final_keys: list[str] = []
        try:
            staged_keys = await self._stage_assets(restore.id, archive)
            restored_counts, final_keys = await self._restore_records(
                archive, target_organization_id, users, staged_keys
            )
            await self.session.commit()
            await self._delete_blobs(staged_keys)
            restore.status = OrganizationRestoreStatus.COMPLETED
            restore.finished_at = self.clock()
            restore.summary = {"restored": restored_counts}
            await self.session.commit()
            return restore
        except BaseException as error:
            await self.session.rollback()
            await self._delete_blobs(final_keys + staged_keys)
            stored = await self.session.get(OrganizationRestore, restore.id)
            if stored is not None:
                stored.status = OrganizationRestoreStatus.FAILED
                stored.finished_at = self.clock()
                stored.safe_error = _safe_error(error)
                await self.session.commit()
            if isinstance(error, SignalScopeError):
                raise
            raise ServiceUnavailableError("Organization restore failed.") from error

    async def _resolve_users(
        self, archive: OrganizationArchive, mappings: Mapping[str, uuid.UUID]
    ) -> dict[uuid.UUID, uuid.UUID]:
        referenced = _referenced_user_ids(archive)
        resolved: dict[uuid.UUID, uuid.UUID] = {}
        used: set[uuid.UUID] = set()
        for source_id in referenced:
            target_id = mappings.get(str(source_id), source_id)
            if target_id in used:
                raise InvalidInputError("Two archived users cannot map to the same user.")
            user = await self.session.get(User, target_id)
            if user is None or not user.is_active:
                raise InvalidInputError(
                    f"Archived user requires an active user mapping: {source_id}"
                )
            resolved[source_id] = target_id
            used.add(target_id)
        return resolved

    async def _stage_assets(self, restore_id: uuid.UUID, archive: OrganizationArchive) -> list[str]:
        keys: list[str] = []
        for row in archive.sections.get("document_assets", ()):
            asset_id = _uuid(row.get("id"), "asset id")
            path = f"assets/{asset_id}"
            content = archive.assets[path]
            key = f"organization-restore-staging/{restore_id}/{asset_id}"
            await self.blobs.put(key, content)
            keys.append(key)
        return keys

    async def _restore_records(
        self,
        archive: OrganizationArchive,
        target_id: uuid.UUID,
        users: Mapping[uuid.UUID, uuid.UUID],
        staged_keys: Sequence[str],
    ) -> tuple[dict[str, int], list[str]]:
        counts: dict[str, int] = {}
        id_map: dict[uuid.UUID, uuid.UUID] = {}

        await self._add_rows(
            Source,
            archive,
            "sources",
            counts,
            id_map,
            lambda _row: {"organization_id": target_id},
        )
        await self._add_rows(Document, archive, "documents", counts, id_map)
        await self._add_rows(DocumentRevision, archive, "document_revisions", counts, id_map)
        await self._add_rows(DocumentChunk, archive, "document_chunks", counts, id_map)

        await self._restore_entities(archive, counts, id_map)
        await self._restore_claims(archive, counts, id_map)
        await self._restore_events(archive, counts, id_map)
        await self._add_rows(
            EntityMention,
            archive,
            "entity_mentions",
            counts,
            id_map,
            lambda row: {"entity_id": _mapped(row, "entity_id", id_map)},
        )
        await self._add_rows(
            ClaimEvidence,
            archive,
            "claim_evidence",
            counts,
            id_map,
            lambda row: {"claim_id": _mapped(row, "claim_id", id_map)},
        )
        await self._add_rows(
            EventEvidence,
            archive,
            "event_evidence",
            counts,
            id_map,
            lambda row: {"event_id": _mapped(row, "event_id", id_map)},
        )

        await self._add_rows(
            EventCluster,
            archive,
            "event_clusters",
            counts,
            id_map,
            lambda _row: {"organization_id": target_id},
        )
        await self._add_rows(
            EventClusterMember,
            archive,
            "event_cluster_members",
            counts,
            id_map,
            lambda row: {
                "event_id": _mapped(row, "event_id", id_map),
                "cluster_id": _mapped(row, "cluster_id", id_map),
            },
        )
        await self._add_rows(
            Investigation,
            archive,
            "investigations",
            counts,
            id_map,
            lambda row: {
                "organization_id": target_id,
                "created_by_user_id": _mapped_user(row.get("created_by_user_id"), users),
            },
        )
        await self._add_rows(
            InvestigationItem,
            archive,
            "investigation_items",
            counts,
            id_map,
            lambda row: {"reference_id": _mapped(row, "reference_id", id_map)},
        )
        await self._add_rows(
            InvestigationCollaborator,
            archive,
            "investigation_collaborators",
            counts,
            id_map,
            lambda row: {"user_id": _mapped_user(row.get("user_id"), users)},
        )
        await self._add_rows(
            ResearchSession,
            archive,
            "research_sessions",
            counts,
            id_map,
            lambda _row: {"organization_id": target_id},
        )
        await self._add_rows(ResearchTurn, archive, "research_turns", counts, id_map)
        await self._restore_memberships(archive, target_id, users, counts)
        await self._add_rows(
            SecurityAuditEvent,
            archive,
            "security_audit",
            counts,
            id_map,
            lambda row: {
                "organization_id": target_id,
                "actor_user_id": _mapped_user(row.get("actor_user_id"), users),
                "resource_id": _optional_mapped(row.get("resource_id"), id_map),
            },
        )
        await self._add_rows(
            OperationAttempt,
            archive,
            "operation_history",
            counts,
            id_map,
            lambda row: {
                "organization_id": target_id,
                "resource_id": _optional_mapped(row.get("resource_id"), id_map),
            },
        )

        final_keys = await self._restore_assets(archive, target_id, staged_keys, counts, id_map)
        return counts, final_keys

    async def _add_rows[Model: DeclarativeBase](
        self,
        model: type[Model],
        archive: OrganizationArchive,
        section: str,
        counts: dict[str, int],
        id_map: dict[uuid.UUID, uuid.UUID],
        overrides: Any | None = None,
    ) -> None:
        rows = archive.sections.get(section, ())
        for row in rows:
            values = _model_values(model, row)
            if "id" in values:
                original_id = values["id"]
                target_row_id = id_map.get(original_id, original_id)
                if await self.session.get(model, target_row_id) is not None:
                    target_row_id = uuid.uuid4()
                values["id"] = target_row_id
                id_map[original_id] = target_row_id
            for key in _FOREIGN_ID_FIELDS.get(model, ()):
                if key in values and values[key] is not None:
                    values[key] = id_map.get(values[key], values[key])
            if overrides is not None:
                values.update(overrides(row))
            self.session.add(model(**values))
        if rows:
            await self.session.flush()
        counts[section] = len(rows)

    async def _restore_entities(
        self,
        archive: OrganizationArchive,
        counts: dict[str, int],
        id_map: dict[uuid.UUID, uuid.UUID],
    ) -> None:
        created = 0
        reused = 0
        for row in archive.sections.get("entities", ()):
            source_id = _uuid(row.get("id"), "entity id")
            existing = await self.session.scalar(
                select(Entity).where(
                    Entity.normalized_name == row.get("normalized_name"),
                    Entity.entity_type == row.get("entity_type"),
                )
            )
            if existing is not None:
                id_map[source_id] = existing.id
                reused += 1
                continue
            target_id = source_id
            if await self.session.get(Entity, target_id) is not None:
                target_id = uuid.uuid4()
            values = _model_values(Entity, row) | {"id": target_id}
            self.session.add(Entity(**values))
            id_map[source_id] = target_id
            created += 1
        if created:
            await self.session.flush()
        counts["entities"] = created
        counts["entities_reused"] = reused

    async def _restore_claims(
        self,
        archive: OrganizationArchive,
        counts: dict[str, int],
        id_map: dict[uuid.UUID, uuid.UUID],
    ) -> None:
        created = 0
        reused = 0
        for row in archive.sections.get("claims", ()):
            source_id = _uuid(row.get("id"), "claim id")
            existing = await self.session.scalar(
                select(Claim).where(
                    Claim.normalized_text == row.get("normalized_text"),
                    Claim.claim_type == row.get("claim_type"),
                )
            )
            if existing is not None:
                id_map[source_id] = existing.id
                reused += 1
                continue
            target_id = source_id
            if await self.session.get(Claim, target_id) is not None:
                target_id = uuid.uuid4()
            values = _model_values(Claim, row) | {"id": target_id}
            self.session.add(Claim(**values))
            id_map[source_id] = target_id
            created += 1
        if created:
            await self.session.flush()
        counts["claims"] = created
        counts["claims_reused"] = reused

    async def _restore_events(
        self,
        archive: OrganizationArchive,
        counts: dict[str, int],
        id_map: dict[uuid.UUID, uuid.UUID],
    ) -> None:
        rows = archive.sections.get("events", ())
        for row in rows:
            source_id = _uuid(row.get("id"), "event id")
            target_id = source_id
            if await self.session.get(Event, target_id) is not None:
                target_id = uuid.uuid4()
            self.session.add(Event(**(_model_values(Event, row) | {"id": target_id})))
            id_map[source_id] = target_id
        if rows:
            await self.session.flush()
        counts["events"] = len(rows)

    async def _restore_memberships(
        self,
        archive: OrganizationArchive,
        target_id: uuid.UUID,
        users: Mapping[uuid.UUID, uuid.UUID],
        counts: dict[str, int],
    ) -> None:
        rows = archive.sections.get("memberships", ())
        for row in rows:
            user_id = _mapped_user(row.get("user_id"), users)
            existing = await self.session.get(OrganizationMembership, (target_id, user_id))
            values = _model_values(OrganizationMembership, row)
            if existing is None:
                values.update({"organization_id": target_id, "user_id": user_id})
                self.session.add(OrganizationMembership(**values))
            else:
                existing.role = values["role"]
        if rows:
            await self.session.flush()
        counts["memberships"] = len(rows)

    async def _restore_assets(
        self,
        archive: OrganizationArchive,
        target_id: uuid.UUID,
        staged_keys: Sequence[str],
        counts: dict[str, int],
        id_map: dict[uuid.UUID, uuid.UUID],
    ) -> list[str]:
        rows = archive.sections.get("document_assets", ())
        final_keys: list[str] = []
        for row, staged_key in zip(rows, staged_keys, strict=True):
            source_asset_id = _uuid(row.get("id"), "asset id")
            asset_id = source_asset_id
            if await self.session.get(DocumentAsset, asset_id) is not None:
                asset_id = uuid.uuid4()
            id_map[source_asset_id] = asset_id
            content = await self.blobs.get(staged_key)
            final_key = f"document-assets/{target_id}/{asset_id}"
            await self.blobs.put(final_key, content)
            final_keys.append(final_key)
            values = _model_values(DocumentAsset, row)
            values["id"] = asset_id
            values["storage_key"] = final_key
            values["document_id"] = id_map.get(values["document_id"], values["document_id"])
            self.session.add(DocumentAsset(**values))
        if rows:
            await self.session.flush()
        counts["document_assets"] = len(rows)
        return final_keys

    def _require_asset_content(self, archive: OrganizationArchive) -> None:
        for row in archive.sections.get("document_assets", ()):
            asset_id = _uuid(row.get("id"), "asset id")
            path = f"assets/{asset_id}"
            content = archive.assets.get(path)
            if content is None:
                raise InvalidInputError(f"Archive asset content is missing: {asset_id}")
            if len(content) != row.get("size_bytes") or hashlib.sha256(
                content
            ).hexdigest() != row.get("sha256"):
                raise InvalidInputError(
                    f"Archive asset content does not match its record: {asset_id}"
                )

    async def _delete_blobs(self, keys: Sequence[str]) -> None:
        for key in reversed(keys):
            with suppress(SignalScopeError):
                await self.blobs.delete(key)


_FOREIGN_ID_FIELDS: dict[type[DeclarativeBase], tuple[str, ...]] = {
    Document: ("source_id",),
    DocumentRevision: ("document_id",),
    DocumentChunk: ("document_id",),
    EntityMention: ("document_id", "chunk_id"),
    ClaimEvidence: ("chunk_id",),
    EventEvidence: ("chunk_id",),
    EventClusterMember: (),
    InvestigationItem: ("investigation_id",),
    InvestigationCollaborator: ("investigation_id",),
    ResearchSession: ("source_id",),
    ResearchTurn: ("session_id",),
}


def _model_values[Model: DeclarativeBase](
    model: type[Model], row: Mapping[str, Any]
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for attribute in inspect(model).column_attrs:
        key = attribute.key
        if key not in row:
            continue
        column = attribute.columns[0]
        values[key] = _convert(row[key], column.type.python_type)
    return values


def _convert(value: Any, python_type: type[Any]) -> Any:
    if value is None or isinstance(value, python_type):
        return value
    if python_type is uuid.UUID:
        return uuid.UUID(value)
    if python_type is datetime:
        return datetime.fromisoformat(value)
    if issubclass(python_type, Enum):
        return python_type(value)
    return value


def _referenced_user_ids(archive: OrganizationArchive) -> tuple[uuid.UUID, ...]:
    references = (
        ("organization", "created_by_user_id"),
        ("memberships", "user_id"),
        ("investigations", "created_by_user_id"),
        ("investigation_collaborators", "user_id"),
        ("security_audit", "actor_user_id"),
    )
    values = {
        uuid.UUID(value)
        for section, key in references
        for row in archive.sections.get(section, ())
        if isinstance((value := row.get(key)), str)
    }
    return tuple(sorted(values))


def _uuid(value: Any, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise InvalidInputError(f"Archive {label} is not valid.") from error


def _mapped(row: Mapping[str, Any], key: str, id_map: Mapping[uuid.UUID, uuid.UUID]) -> uuid.UUID:
    value = _uuid(row.get(key), key.replace("_", " "))
    return id_map.get(value, value)


def _optional_mapped(value: Any, id_map: Mapping[uuid.UUID, uuid.UUID]) -> uuid.UUID | None:
    if value is None:
        return None
    parsed = _uuid(value, "resource id")
    return id_map.get(parsed, parsed)


def _mapped_user(value: Any, users: Mapping[uuid.UUID, uuid.UUID]) -> uuid.UUID | None:
    if value is None:
        return None
    source_id = _uuid(value, "user id")
    try:
        return users[source_id]
    except KeyError as error:
        raise InvalidInputError(f"Archived user requires a user mapping: {source_id}") from error


def _safe_error(error: BaseException) -> str:
    if isinstance(error, SignalScopeError):
        return short_error_message(str(error))
    return "Organization restore failed."
