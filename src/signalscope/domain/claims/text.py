import re

WHITESPACE = re.compile(r"\s+")


def normalize_claim_text(text: str) -> str:
    """Return the form of a claim that is used to tell claims apart.

    Spaces are trimmed and collapsed, and case is folded. Punctuation and
    numbers stay, because they change what a claim says. Two claims only match
    when this text is the same: there is no matching by meaning.
    """
    return WHITESPACE.sub(" ", text).strip().casefold()


def normalize_claim_type(claim_type: str) -> str:
    """Return the stored form of a claim type: trimmed and lower case.

    Raises ValueError for a blank type.
    """
    normalized = claim_type.strip().lower()
    if not normalized:
        raise ValueError("Claim type must not be empty.")
    return normalized
