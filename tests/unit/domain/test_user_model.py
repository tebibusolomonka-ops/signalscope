import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.db.models import Base
from signalscope.domain.users.email import InvalidEmailError, normalize_email
from signalscope.domain.users.model import User


def test_users_table() -> None:
    sql = str(CreateTable(User.__table__).compile(dialect=postgresql.dialect()))

    for column in [
        "email VARCHAR(254) NOT NULL",
        "normalized_email VARCHAR(254) NOT NULL",
        "display_name VARCHAR(200) NOT NULL",
        "is_active BOOLEAN DEFAULT true NOT NULL",
        "is_system_admin BOOLEAN DEFAULT false NOT NULL",
    ]:
        assert column in sql
    assert "UNIQUE (normalized_email)" in sql
    assert "CHECK (btrim(display_name) <> '')" in sql
    # Passwords live in their own table.
    assert "password" not in sql
    assert Base.metadata.tables["users"] is User.__table__


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("  Ana@Example.ORG ", "ana@example.org"),
        ("ANA.SILVA+news@example.org", "ana.silva+news@example.org"),
        ("ａｎａ@example.org", "ana@example.org"),
        ("Straße@example.de", "strasse@example.de"),
    ],
    ids=["trim and case", "no provider rules", "width", "case folding"],
)
def test_normalize_email(email: str, expected: str) -> None:
    assert normalize_email(email) == expected


@pytest.mark.parametrize(
    "email",
    ["", "  ", "ana", "ana@", "@example.org", "ana@@example.org", "ana@localhost", "a na@x.org"]
    + ["a" * 250 + "@x.org"],
    ids=[
        "empty",
        "blank",
        "no at",
        "no domain",
        "no local part",
        "two ats",
        "no dot",
        "space",
        "too long",
    ],
)
def test_invalid_emails(email: str) -> None:
    with pytest.raises(InvalidEmailError):
        normalize_email(email)
