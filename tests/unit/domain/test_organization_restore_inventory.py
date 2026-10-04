from signalscope.domain.organizations.archive_reader import OrganizationArchive
from signalscope.domain.organizations.export_verification import OrganizationExportVerification
from signalscope.domain.organizations.restore_inventory import OrganizationRestoreInventoryService


def archive(sections: dict[str, tuple[dict[str, object], ...]]) -> OrganizationArchive:
    return OrganizationArchive(
        manifest={},
        sections=sections,
        verification=OrganizationExportVerification(True, "2", 0, 0, ()),
    )


def test_reports_restore_inventory() -> None:
    result = OrganizationRestoreInventoryService().build(
        archive(
            {
                "sources": ({"id": "source"},),
                "documents": ({"id": "document"},),
                "document_revisions": ({"id": "revision"},),
                "entities": ({"id": "entity"},),
                "entity_mentions": ({"id": "mention"},),
                "claims": ({"id": "claim"},),
                "claim_evidence": ({"id": "evidence"},),
                "events": ({"id": "event"},),
                "event_evidence": ({"id": "event-evidence"},),
                "event_clusters": ({"id": "cluster"},),
                "research_sessions": ({"id": "session"},),
                "investigations": ({"id": "investigation"},),
                "memberships": ({"user_id": "user-a"},),
                "investigation_collaborators": ({"user_id": "user-b"},),
                "security_audit": ({"id": "audit"},),
                "operation_history": ({"id": "history"},),
                "document_assets": ({"id": "asset"},),
            }
        )
    )

    assert result.counts == {
        "sources": 1,
        "documents": 1,
        "revisions": 1,
        "entities": 1,
        "entity_evidence": 1,
        "claims": 1,
        "claim_evidence": 1,
        "events": 1,
        "event_evidence": 1,
        "clusters": 1,
        "research_sessions": 1,
        "investigations": 1,
        "memberships": 1,
        "audit_history": 2,
        "assets": 1,
    }
    assert result.referenced_user_ids == ("user-a", "user-b")
    assert result.asset_count == 1


def test_reports_empty_sections() -> None:
    result = OrganizationRestoreInventoryService().build(archive({}))

    assert all(value == 0 for value in result.counts.values())
    assert result.referenced_user_ids == ()
