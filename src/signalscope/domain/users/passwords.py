"""Password hashing with Argon2id, through pwdlib.

Passwords and hashes never appear in errors or logs.
"""

from dataclasses import dataclass

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher

from signalscope.core.errors import InvalidInputError

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 1024


class InvalidPasswordError(InvalidInputError):
    default_message = (
        f"Password must be from {PASSWORD_MIN_LENGTH} to {PASSWORD_MAX_LENGTH} characters."
    )


def check_password_policy(password: str) -> None:
    """Only length is checked. There are no rules about kinds of characters."""
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise InvalidPasswordError()


@dataclass(frozen=True, slots=True)
class PasswordCheck:
    valid: bool
    # A new hash to store when the stored one uses older settings. None otherwise.
    new_hash: str | None = None


class PasswordHasher:
    """Hashes and checks passwords with Argon2id.

    The default settings are the argon2-cffi defaults. Tests pass a cheaper
    Argon2Hasher, so production settings are never weakened.
    """

    def __init__(self, hasher: Argon2Hasher | None = None) -> None:
        self._hashing = PasswordHash((hasher or Argon2Hasher(),))

    def hash_password(self, password: str) -> str:
        """A salted Argon2id hash. Raises InvalidPasswordError for a bad length."""
        check_password_policy(password)
        return self._hashing.hash(password)

    def verify_password(self, password: str, password_hash: str) -> PasswordCheck:
        """Whether password matches, and a new hash when the old one needs updating.

        A password of a length the policy does not allow, or a hash that is not
        Argon2, never matches. No error says which.
        """
        if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
            return PasswordCheck(valid=False)
        try:
            valid, new_hash = self._hashing.verify_and_update(password, password_hash)
        except UnknownHashError:
            return PasswordCheck(valid=False)
        return PasswordCheck(valid=valid, new_hash=new_hash)

    def needs_rehash(self, password_hash: str) -> bool:
        """Whether a stored hash uses other settings than the current ones."""
        hasher = self._hashing.current_hasher
        if not hasher.identify(password_hash):
            return True
        return hasher.check_needs_rehash(password_hash)
