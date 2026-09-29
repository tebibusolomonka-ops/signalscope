import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, ForbiddenError, InvalidInputError, NotFoundError
from signalscope.db.errors import is_unique_violation
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import (
    ORGANIZATION_NAME_MAX_LENGTH,
    Organization,
    normalize_slug,
)
from signalscope.domain.users.model import User

# Roles an admin may give, change and remove. Owners and admins are managed by owners.
ADMIN_MANAGED_ROLES = frozenset({OrganizationRole.MEMBER, OrganizationRole.VIEWER})
LAST_OWNER_ERROR = "An organization must keep at least one owner."


@dataclass(frozen=True, slots=True)
class MemberWithUser:
    membership: OrganizationMembership
    user: User


class OrganizationService:
    """Organizations and who belongs to them, with role rules.

    Owners manage all members. Admins manage members and viewers only.
    Members and viewers manage nobody. A system admin may manage any
    organization, as a recovery path. An organization always keeps at least
    one owner. Organizations a user does not belong to are reported as not
    found, so their existence does not leak.

    Membership changes lock the organization row, so two changes at the same
    time cannot both remove the last owner. Writes commit before they return.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, actor: User, name: str, slug: str) -> Organization:
        """Create an organization. The creator becomes its owner."""
        clean_name = name.strip()
        if not clean_name or len(clean_name) > ORGANIZATION_NAME_MAX_LENGTH:
            raise InvalidInputError(
                f"Organization name must be from 1 to {ORGANIZATION_NAME_MAX_LENGTH} characters."
            )
        organization = Organization(
            name=clean_name, slug=normalize_slug(slug), created_by_user_id=actor.id
        )
        self.session.add(organization)
        try:
            await self.session.flush()
            self.session.add(
                OrganizationMembership(
                    organization_id=organization.id,
                    user_id=actor.id,
                    role=OrganizationRole.OWNER,
                )
            )
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if is_unique_violation(error):
                raise ConflictError("An organization with this slug already exists.") from error
            raise
        except Exception:
            await self.session.rollback()
            raise
        return organization

    async def get(self, actor: User, organization_id: uuid.UUID) -> Organization:
        """An organization the actor belongs to, or any one for a system admin."""
        organization = await self.session.get(Organization, organization_id)
        if organization is None or (
            not actor.is_system_admin and await self.role_of(actor.id, organization_id) is None
        ):
            raise NotFoundError("Organization was not found.")
        return organization

    async def list_for_user(self, actor: User) -> list[tuple[Organization, OrganizationRole]]:
        """The actor's organizations and their role in each, by name."""
        rows = await self.session.execute(
            select(Organization, OrganizationMembership.role)
            .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
            .where(OrganizationMembership.user_id == actor.id)
            .order_by(Organization.name, Organization.id)
        )
        return [(organization, role) for organization, role in rows]

    async def list_members(self, actor: User, organization_id: uuid.UUID) -> list[MemberWithUser]:
        """Every member with their role, owners first. Any member may look."""
        await self.get(actor, organization_id)
        rows = await self.session.execute(
            select(OrganizationMembership, User)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(OrganizationMembership.organization_id == organization_id)
            .order_by(User.display_name, User.id)
        )
        members = [MemberWithUser(membership, user) for membership, user in rows]
        order = list(OrganizationRole)
        return sorted(members, key=lambda member: order.index(member.membership.role))

    async def role_of(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> OrganizationRole | None:
        membership = await self.session.get(OrganizationMembership, (organization_id, user_id))
        return None if membership is None else membership.role

    async def add_member(
        self,
        actor: User,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        role: OrganizationRole,
    ) -> OrganizationMembership:
        """Add an active user with a role."""
        await self._lock(actor, organization_id)
        await self._check_manager(actor, organization_id, new_role=role)
        user = await self.session.get(User, user_id)
        if user is None or not user.is_active:
            await self.session.rollback()
            raise NotFoundError("User was not found.")
        membership = OrganizationMembership(
            organization_id=organization_id, user_id=user_id, role=role
        )
        self.session.add(membership)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if is_unique_violation(error):
                raise ConflictError("The user is already a member.") from error
            raise
        return membership

    async def change_member_role(
        self,
        actor: User,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        role: OrganizationRole,
    ) -> OrganizationMembership:
        await self._lock(actor, organization_id)
        membership = await self._membership(organization_id, user_id)
        await self._check_manager(
            actor, organization_id, current_role=membership.role, new_role=role
        )
        if membership.role is OrganizationRole.OWNER and role is not OrganizationRole.OWNER:
            await self._keep_an_owner(organization_id)
        membership.role = role
        await self._commit()
        return membership

    async def remove_member(
        self, actor: User, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        await self._lock(actor, organization_id)
        membership = await self._membership(organization_id, user_id)
        await self._check_manager(actor, organization_id, current_role=membership.role)
        if membership.role is OrganizationRole.OWNER:
            await self._keep_an_owner(organization_id)
        await self.session.delete(membership)
        await self._commit()

    async def _lock(self, actor: User, organization_id: uuid.UUID) -> None:
        """Lock the organization row for a membership change, or say it was not found."""
        organization = await self.session.get(
            Organization, organization_id, with_for_update=True, populate_existing=True
        )
        if organization is None or (
            not actor.is_system_admin and await self.role_of(actor.id, organization_id) is None
        ):
            await self.session.rollback()
            raise NotFoundError("Organization was not found.")

    async def _membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationMembership:
        membership = await self.session.get(
            OrganizationMembership, (organization_id, user_id), populate_existing=True
        )
        if membership is None:
            await self.session.rollback()
            raise NotFoundError("Member was not found.")
        return membership

    async def _check_manager(
        self,
        actor: User,
        organization_id: uuid.UUID,
        *,
        current_role: OrganizationRole | None = None,
        new_role: OrganizationRole | None = None,
    ) -> None:
        """Owners and system admins manage anyone; admins only members and viewers."""
        if actor.is_system_admin:
            return
        actor_role = await self.role_of(actor.id, organization_id)
        if actor_role is OrganizationRole.OWNER:
            return
        touched = {role for role in (current_role, new_role) if role is not None}
        if actor_role is OrganizationRole.ADMIN and touched <= ADMIN_MANAGED_ROLES:
            return
        await self.session.rollback()
        raise ForbiddenError("You do not have permission to manage these members.")

    async def _keep_an_owner(self, organization_id: uuid.UUID) -> None:
        """Refuse a change that would leave the organization without an owner."""
        owners = await self.session.scalar(
            select(func.count())
            .select_from(OrganizationMembership)
            .where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.role == OrganizationRole.OWNER,
            )
        )
        if (owners or 0) <= 1:
            await self.session.rollback()
            raise ConflictError(LAST_OWNER_ERROR)

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
