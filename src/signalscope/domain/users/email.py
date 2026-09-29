import unicodedata

from signalscope.core.errors import InvalidInputError

# The longest address that fits in SMTP paths.
EMAIL_MAX_LENGTH = 254


class InvalidEmailError(InvalidInputError):
    default_message = "Email address is not valid."


def normalize_email(email: str) -> str:
    """Return the form of an email address used to tell accounts apart.

    NFKC normalization, trimmed, and case folded. Nothing provider specific
    is done: dots and plus signs stay, so "a.b@example.org" and
    "ab@example.org" are different accounts. Raises InvalidEmailError when
    the address is clearly not one.
    """
    normalized = unicodedata.normalize("NFKC", email).strip().casefold()
    local, at, domain = normalized.rpartition("@")
    if (
        not at
        or not local
        or not domain
        or "@" in local
        or "." not in domain.strip(".")
        or any(character.isspace() for character in normalized)
        or len(normalized) > EMAIL_MAX_LENGTH
    ):
        raise InvalidEmailError()
    return normalized
