import hashlib

from signalscope.domain.users.authentication import hash_token


def test_hash_token_is_sha256_hex() -> None:
    assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()
    assert len(hash_token("any token")) == 64
    assert hash_token("abc") == hash_token("abc").lower()
