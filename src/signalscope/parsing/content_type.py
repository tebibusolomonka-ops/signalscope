import codecs
from email.message import Message


def content_charset(content_type: str) -> str | None:
    """Return the charset of a media type such as "text/plain; charset=utf-8".

    The result is Python's name for the encoding. It is None when there is no
    charset or Python does not know it.
    """
    message = Message()
    message["content-type"] = content_type
    charset = message.get_content_charset()
    if charset is None:
        return None
    try:
        return codecs.lookup(charset).name
    except LookupError:
        return None


def media_type(content_type: str) -> str:
    """Return a media type without parameters, so "Text/HTML; charset=utf-8" becomes "text/html"."""
    return content_type.split(";", 1)[0].strip().lower()
