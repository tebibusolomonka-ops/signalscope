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


def normalize_entity_type(entity_type: str) -> str:
    """Return the stored form of an entity type: trimmed and lower case.

    "PERSON", "Person" and " person " all become "person". Nothing else is
    changed, and no synonyms are guessed. Raises ValueError for a blank type.
    """
    normalized = entity_type.strip().lower()
    if not normalized:
        raise ValueError("Entity type must not be empty.")
    return normalized
