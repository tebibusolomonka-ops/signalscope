from signalscope.domain.users.login_throttle import login_identifier


def test_login_identifier_is_stable_sha256_without_email() -> None:
    first = login_identifier(" Ana@Example.org ")
    second = login_identifier("ana@example.org")

    assert first == second
    assert len(first) == 64
    assert "ana" not in first


def test_invalid_email_still_has_stable_identifier() -> None:
    assert login_identifier(" BAD ") == login_identifier("bad")
