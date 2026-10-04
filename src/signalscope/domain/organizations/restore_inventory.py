from dataclasses import dataclass

from signalscope.domain.organizations.archive_reader import OrganizationArchive


@dataclass(frozen=True, slots=True)
class OrganizationRestoreInventory:
    counts: dict[str, int]
    referenced_user_ids: tuple[str, ...]
    asset_count: int


class OrganizationRestoreInventoryService:
    """Describe an archive without changing database state."""

    def build(self, archive: OrganizationArchive) -> OrganizationRestoreInventory:
        sections = archive.sections
        counts = {
            "sources": len(sections.get("sources", ())),
            "documents": len(sections.get("documents", ())),
            "revisions": len(sections.get("document_revisions", ())),
            "entities": len(sections.get("entities", ())),
            "entity_evidence": len(sections.get("entity_mentions", ())),
            "claims": len(sections.get("claims", ())),
            "claim_evidence": len(sections.get("claim_evidence", ())),
            "events": len(sections.get("events", ())),
            "event_evidence": len(sections.get("event_evidence", ())),
            "clusters": len(sections.get("event_clusters", ())),
            "research_sessions": len(sections.get("research_sessions", ())),
            "investigations": len(sections.get("investigations", ())),
            "memberships": len(sections.get("memberships", ())),
            "audit_history": len(sections.get("security_audit", ()))
            + len(sections.get("operation_history", ())),
            "assets": len(sections.get("document_assets", ())),
        }
        users = {
            str(row["user_id"])
            for section in ("memberships", "investigation_collaborators")
            for row in sections.get(section, ())
            if row.get("user_id") is not None
        }
        return OrganizationRestoreInventory(
            counts=counts,
            referenced_user_ids=tuple(sorted(users)),
            asset_count=counts["assets"],
        )
