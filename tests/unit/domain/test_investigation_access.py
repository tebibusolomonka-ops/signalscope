import uuid

import pytest

from signalscope.domain.investigations.access import InvestigationPermission, permissions_for
from signalscope.domain.investigations.collaborator import CollaboratorRole
from signalscope.domain.organizations.membership import OrganizationRole

VIEW = InvestigationPermission.VIEW
EDIT = InvestigationPermission.EDIT
ALL = set(InvestigationPermission)
ORGANIZATION = uuid.uuid4()


@pytest.mark.parametrize(
    ("organization_role", "collaborator_role", "expected"),
    [
        (OrganizationRole.OWNER, None, ALL),
        (OrganizationRole.ADMIN, None, ALL),
        (OrganizationRole.ADMIN, CollaboratorRole.VIEWER, ALL),
        (OrganizationRole.MEMBER, None, set()),
        (OrganizationRole.VIEWER, None, set()),
        (OrganizationRole.MEMBER, CollaboratorRole.OWNER, ALL),
        (OrganizationRole.MEMBER, CollaboratorRole.EDITOR, {VIEW, EDIT}),
        (OrganizationRole.VIEWER, CollaboratorRole.VIEWER, {VIEW}),
        (None, None, set()),
        # A collaborator who left the organization keeps no access.
        (None, CollaboratorRole.OWNER, set()),
    ],
)
def test_organization_investigation(
    organization_role: OrganizationRole | None,
    collaborator_role: CollaboratorRole | None,
    expected: set[InvestigationPermission],
) -> None:
    found = permissions_for(
        system_admin=False,
        organization_id=ORGANIZATION,
        organization_role=organization_role,
        collaborator_role=collaborator_role,
    )

    assert found == expected


@pytest.mark.parametrize("organization_id", [ORGANIZATION, None])
def test_system_admin_has_full_access(organization_id: uuid.UUID | None) -> None:
    found = permissions_for(
        system_admin=True,
        organization_id=organization_id,
        organization_role=None,
        collaborator_role=None,
    )

    assert found == ALL


@pytest.mark.parametrize("organization_role", list(OrganizationRole))
def test_legacy_investigation_is_for_system_admins_only(
    organization_role: OrganizationRole,
) -> None:
    found = permissions_for(
        system_admin=False,
        organization_id=None,
        organization_role=organization_role,
        collaborator_role=CollaboratorRole.OWNER,
    )

    assert found == set()
