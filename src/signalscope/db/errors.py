from sqlalchemy.exc import IntegrityError

UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"


def is_unique_violation(error: IntegrityError) -> bool:
    return getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION


def is_foreign_key_violation(error: IntegrityError) -> bool:
    return getattr(error.orig, "sqlstate", None) == FOREIGN_KEY_VIOLATION
