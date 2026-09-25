from sqlalchemy.exc import IntegrityError

from signalscope.db.errors import is_foreign_key_violation, is_unique_violation


class DriverError(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        self.sqlstate = sqlstate


def integrity_error(sqlstate: str | None) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, DriverError(sqlstate))


def test_unique_violation_is_detected() -> None:
    assert is_unique_violation(integrity_error("23505"))


def test_other_integrity_errors_are_not_unique_violations() -> None:
    assert not is_unique_violation(integrity_error("23503"))
    assert not is_unique_violation(integrity_error(None))


def test_foreign_key_violation_is_detected() -> None:
    assert is_foreign_key_violation(integrity_error("23503"))
    assert not is_foreign_key_violation(integrity_error("23505"))
    assert not is_foreign_key_violation(integrity_error(None))
