import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.organizations.model import InvalidSlugError, Organization, normalize_slug


def test_organizations_table() -> None:
    sql = str(CreateTable(Organization.__table__).compile(dialect=postgresql.dialect()))

    assert "name VARCHAR(200) NOT NULL" in sql
    assert "slug VARCHAR(63) NOT NULL" in sql
    assert "UNIQUE (slug)" in sql
    assert "CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$')" in sql
    assert "FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE RESTRICT" in sql
    assert Base.metadata.tables["organizations"] is Organization.__table__


@pytest.mark.parametrize(
    ("slug", "expected"),
    [(" Harbour-Watch ", "harbour-watch"), ("news2026", "news2026"), ("a", "a")],
)
def test_valid_slugs(slug: str, expected: str) -> None:
    assert normalize_slug(slug) == expected


@pytest.mark.parametrize(
    "slug",
    ["", "-news", "news-", "news--desk", "news desk", "news_desk", "nëws", "a" * 64],
    ids=[
        "empty",
        "leading hyphen",
        "trailing hyphen",
        "double hyphen",
        "space",
        "underscore",
        "accent",
        "too long",
    ],
)
def test_invalid_slugs(slug: str) -> None:
    with pytest.raises(InvalidSlugError):
        normalize_slug(slug)


def test_membership_table() -> None:
    from signalscope.domain.organizations.membership import (
        OrganizationMembership,
        OrganizationRole,
    )

    sql = str(CreateTable(OrganizationMembership.__table__).compile(dialect=postgresql.dialect()))

    assert "PRIMARY KEY (organization_id, user_id)" in sql
    assert "REFERENCES organizations (id) ON DELETE CASCADE" in sql
    assert "REFERENCES users (id) ON DELETE RESTRICT" in sql
    assert "CHECK (role IN ('owner', 'admin', 'member', 'viewer'))" in sql
    assert [role.value for role in OrganizationRole] == ["owner", "admin", "member", "viewer"]
    assert {index.name for index in OrganizationMembership.__table__.indexes} == {
        "ix_organization_memberships_user_id"
    }
