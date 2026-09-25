def normalize_language(value: str) -> str:
    """Trim and lowercase a language tag, so "EN" and " en " both become "en".

    Tags are not checked against a list, because external sources send all
    kinds of values.
    """
    language = value.strip().lower()
    if not language:
        raise ValueError("language must not be empty")
    return language
