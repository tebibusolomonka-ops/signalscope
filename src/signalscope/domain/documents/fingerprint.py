import hashlib

# Keeps the fields apart, so moving text from the title to the content changes the hash.
SEPARATOR = "\x1f"


def content_fingerprint(*, title: str | None, content: str | None, url: str | None) -> str | None:
    """SHA-256 hex digest of the title, content and URL, or None when all are empty.

    Only line endings and surrounding whitespace are normalized, so any real
    change to the text gives a new fingerprint.
    """
    parts = [_normalize(value) for value in (title, content, url)]
    if not any(parts):
        return None
    return hashlib.sha256(SEPARATOR.join(parts).encode()).hexdigest()


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()
