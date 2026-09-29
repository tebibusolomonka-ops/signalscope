import pytest
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from password_helpers import OTHER_PASSWORD, TEST_PASSWORD, fast_hasher
from signalscope.db.models import Base
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.passwords import (
    InvalidPasswordError,
    PasswordHasher,
    check_password_policy,
)


def test_hash_is_argon2id_and_not_the_password() -> None:
    password_hash = fast_hasher().hash_password(TEST_PASSWORD)

    assert password_hash.startswith("$argon2id$")
    assert TEST_PASSWORD not in password_hash


def test_same_password_gives_different_salted_hashes() -> None:
    hasher = fast_hasher()

    assert hasher.hash_password(TEST_PASSWORD) != hasher.hash_password(TEST_PASSWORD)


def test_verify() -> None:
    hasher = fast_hasher()
    password_hash = hasher.hash_password(TEST_PASSWORD)

    assert hasher.verify_password(TEST_PASSWORD, password_hash).valid is True
    assert hasher.verify_password(OTHER_PASSWORD, password_hash).valid is False
    # Wrong lengths and hashes that are not Argon2 never match, and never raise.
    assert hasher.verify_password("short", password_hash).valid is False
    assert hasher.verify_password(TEST_PASSWORD, "plain text").valid is False


@pytest.mark.parametrize(
    ("password", "allowed"),
    [("x" * 11, False), ("x" * 12, True), ("x" * 1024, True), ("x" * 1025, False)],
    ids=["11", "12", "1024", "1025"],
)
def test_length_policy(password: str, allowed: bool) -> None:
    if allowed:
        check_password_policy(password)
        fast_hasher().hash_password(password)
    else:
        with pytest.raises(InvalidPasswordError) as error:
            fast_hasher().hash_password(password)
        # The message never holds the password.
        assert password not in str(error.value)
        assert str(error.value) == "Password must be from 12 to 1024 characters."


def test_no_character_class_rules() -> None:
    check_password_policy("all lower case words")


def test_old_settings_are_rehashed() -> None:
    old = PasswordHasher(Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1))
    new = PasswordHasher(Argon2Hasher(time_cost=2, memory_cost=1024, parallelism=1))
    old_hash = old.hash_password(TEST_PASSWORD)

    check = new.verify_password(TEST_PASSWORD, old_hash)

    assert new.needs_rehash(old_hash) is True
    assert check.valid is True and check.new_hash is not None
    assert new.needs_rehash(check.new_hash) is False
    assert old.verify_password(TEST_PASSWORD, old_hash).new_hash is None
    assert new.needs_rehash("not an argon2 hash") is True


def test_default_hasher_uses_argon2_defaults() -> None:
    password_hash = PasswordHasher().hash_password(TEST_PASSWORD)

    assert password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")


def test_credentials_table() -> None:
    sql = str(CreateTable(UserPasswordCredential.__table__).compile(dialect=postgresql.dialect()))

    assert "PRIMARY KEY (user_id)" in sql
    assert "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE" in sql
    assert "password_hash VARCHAR(512) NOT NULL" in sql
    assert "password_changed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in sql
    assert Base.metadata.tables["user_password_credentials"] is UserPasswordCredential.__table__


def test_check_without_account_does_real_work() -> None:
    hasher = fast_hasher()

    hasher.check_without_account(TEST_PASSWORD)
    first = hasher._dummy_hash
    hasher.check_without_account(OTHER_PASSWORD)

    assert first is not None and first.startswith("$argon2id$")
    # One hash is made and then reused.
    assert hasher._dummy_hash == first
