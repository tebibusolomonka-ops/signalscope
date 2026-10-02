from types import SimpleNamespace

from signalscope.domain.organizations.export_inventory import OrganizationExportInventory


def test_inventory_counts_every_safe_collection() -> None:
    organization = SimpleNamespace(id="organization")
    inventory = OrganizationExportInventory(
        organization=(organization,),
        memberships=(SimpleNamespace(),),
        sources=(),
        documents=(SimpleNamespace(), SimpleNamespace()),
        document_revisions=(),
        document_chunks=(),
        entities=(),
        entity_mentions=(),
        claims=(),
        claim_evidence=(),
        events=(),
        event_evidence=(),
        event_clusters=(),
        event_cluster_members=(),
        investigations=(),
        investigation_items=(),
        investigation_collaborators=(),
        research_sessions=(),
        research_turns=(),
        security_audit=(),
        operation_history=(),
    )

    assert inventory.counts["organization"] == 1
    assert inventory.counts["memberships"] == 1
    assert inventory.counts["documents"] == 2
    assert "user_password_credentials" not in inventory.counts
    assert "user_sessions" not in inventory.counts
    assert "organization_invitations" not in inventory.counts
