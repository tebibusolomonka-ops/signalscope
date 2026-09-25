import hashlib
from dataclasses import dataclass

MAX_CHUNK_CHARS = 1200
OVERLAP_CHARS = 200
# Breaks are only looked for after this many characters, so a blank line near
# the start of a chunk cannot make a tiny chunk.
MIN_CHUNK_CHARS = 600
# Tried in this order before any other whitespace.
PREFERRED_BREAKS = ("\n\n", "\n")


@dataclass(frozen=True, slots=True)
class TextChunk:
    position: int
    text: str
    start_char: int
    end_char: int
    text_hash: str


def chunk_text(
    text: str,
    *,
    max_chars: int = MAX_CHUNK_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
    min_chars: int = MIN_CHUNK_CHARS,
) -> list[TextChunk]:
    """Split text into overlapping chunks of at most max_chars characters.

    A chunk ends at the last paragraph break between min_chars and max_chars,
    or else at a line break, or else at other whitespace. Only a single word
    longer than that range is cut in the middle. The next chunk starts at a
    word about overlap_chars before the end of the previous one.

    The text is never changed: chunk.text is always
    text[chunk.start_char:chunk.end_char], and it never starts or ends with
    whitespace.
    """
    if not 0 <= overlap_chars < min_chars <= max_chars:
        raise ValueError("chunk sizes must follow 0 <= overlap_chars < min_chars <= max_chars")
    chunks: list[TextChunk] = []
    start = _skip_whitespace(text, 0)
    while start < len(text):
        end = _chunk_end(text, start, max_chars, min_chars)
        chunks.append(_chunk(len(chunks), text, start, _trim_end(text, start, end)))
        if end == len(text):
            break
        start = _next_start(text, start, end, overlap_chars)
    return chunks


def _chunk_end(text: str, start: int, max_chars: int, min_chars: int) -> int:
    limit = start + max_chars
    if limit >= len(text):
        return len(text)
    lowest = start + min_chars
    for separator in PREFERRED_BREAKS:
        index = text.rfind(separator, lowest, limit)
        if index != -1:
            return index
    for index in range(limit, lowest - 1, -1):
        if text[index].isspace():
            return index
    return limit


def _next_start(text: str, start: int, end: int, overlap_chars: int) -> int:
    candidate = max(end - overlap_chars, start + 1)
    if text[candidate - 1].isspace():
        return _skip_whitespace(text, candidate)
    # Move to the start of the next word, unless the rest is one long word.
    for index in range(candidate, end):
        if text[index].isspace():
            return _skip_whitespace(text, index)
    return candidate


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _trim_end(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def _chunk(position: int, text: str, start: int, end: int) -> TextChunk:
    chunk = text[start:end]
    return TextChunk(
        position=position,
        text=chunk,
        start_char=start,
        end_char=end,
        text_hash=hashlib.sha256(chunk.encode()).hexdigest(),
    )
