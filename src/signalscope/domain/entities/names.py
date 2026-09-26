import re
import unicodedata

WHITESPACE = re.compile(r"\s+")


def normalize_entity_name(name: str) -> str:
    """Return the form of a name that is used to tell entities apart.

    Compatible Unicode forms are unified, spaces are trimmed and collapsed, and
    case is folded, so "  Ángela   Merkel" and "ángela merkel" match.
    Punctuation stays, because it is part of names such as "AT&T" or "O'Brien".
    This is a first, simple identity rule, not real entity resolution.
    """
    return WHITESPACE.sub(" ", unicodedata.normalize("NFKC", name)).strip().casefold()
