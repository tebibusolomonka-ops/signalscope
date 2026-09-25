import json
from typing import Any

from signalscope.parsing.types import DocumentParsingError, ParsedDocument

# Values nested deeper than this are left out.
MAX_DEPTH = 32
# At most this many lines are written, so a huge file cannot make huge text.
MAX_VALUES = 10_000


class JsonParser:
    """Reads application/json documents as one "path: value" line per value.

    For example {"author": {"name": "Jane"}, "tags": ["ai"]} becomes the lines
    "author.name: Jane" and "tags[0]: ai". Keys keep their order. Empty objects
    and lists give no lines. metadata["truncated"] says whether values were
    left out because of the limits.
    """

    def parse(
        self,
        data: bytes,
        *,
        content_type: str,
        filename: str | None = None,
        source_url: str | None = None,
    ) -> ParsedDocument:
        try:
            # json finds the encoding itself, such as UTF-8 with or without a byte order mark.
            value = json.loads(data)
        except RecursionError as error:
            raise DocumentParsingError("JSON is nested too deeply.") from error
        except ValueError as error:
            raise DocumentParsingError("Document is not valid JSON.") from error

        lines = _Lines()
        lines.add(value, path="", depth=0)
        return ParsedDocument(
            text="\n".join(lines.lines),
            title=_title(value),
            metadata={"truncated": lines.truncated},
        )


class _Lines:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.truncated = False

    def add(self, value: Any, path: str, depth: int) -> None:
        if depth > MAX_DEPTH or len(self.lines) >= MAX_VALUES:
            self.truncated = True
            return
        if isinstance(value, dict):
            for key, child in value.items():
                self.add(child, f"{path}.{key}" if path else key, depth + 1)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self.add(child, f"{path}[{index}]", depth + 1)
        else:
            text = value if isinstance(value, str) else json.dumps(value)
            self.lines.append(f"{path}: {text}" if path else text)


def _title(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("title"), str):
        return value["title"].strip() or None
    return None
