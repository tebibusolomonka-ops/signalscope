from enum import StrEnum

from sqlalchemy import Enum


def string_enum(enum_type: type[StrEnum], name: str) -> Enum:
    """Store enum values as text with a check constraint.

    A PostgreSQL enum type is harder to change later, so new values only need
    a new check constraint this way. The constraint is named after name.
    """
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [member.value for member in members],
    )
