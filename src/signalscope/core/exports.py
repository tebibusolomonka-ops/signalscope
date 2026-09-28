from enum import StrEnum

MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"


class ExportFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
