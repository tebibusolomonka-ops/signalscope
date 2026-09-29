"""A fast password hasher for tests.

It still uses real Argon2id, only with low cost settings. Production code keeps
the library defaults.
"""

from pwdlib.hashers.argon2 import Argon2Hasher

from signalscope.domain.users.passwords import PasswordHasher

# Test passwords only. They meet the length policy.
TEST_PASSWORD = "correct horse battery staple"
OTHER_PASSWORD = "another long test password"


def fast_argon2() -> Argon2Hasher:
    return Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1)


def fast_hasher() -> PasswordHasher:
    return PasswordHasher(fast_argon2())
