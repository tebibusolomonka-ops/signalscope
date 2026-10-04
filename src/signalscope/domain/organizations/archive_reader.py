import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any

from signalscope.core.errors import InvalidInputError
from signalscope.domain.organizations.export_archive import FILES
from signalscope.domain.organizations.export_verification import (
    MAX_MEMBER_BYTES,
    OrganizationExportVerification,
    OrganizationExportVerificationService,
)

MAX_ARCHIVE_BYTES = 512_000_000


@dataclass(frozen=True, slots=True)
class OrganizationArchive:
    manifest: dict[str, Any]
    sections: dict[str, tuple[dict[str, Any], ...]]
    verification: OrganizationExportVerification


class OrganizationArchiveReader:
    """Read a verified organization export without writing archive members to disk."""

    def __init__(self, verifier: OrganizationExportVerificationService | None = None) -> None:
        self.verifier = verifier or OrganizationExportVerificationService()

    def read(self, data: bytes) -> OrganizationArchive:
        if len(data) > MAX_ARCHIVE_BYTES:
            raise InvalidInputError("Organization export archive is too large.")
        verification = self.verifier.verify(data)
        if not verification.valid:
            raise InvalidInputError(
                "Organization export archive is not valid: " + "; ".join(verification.problems)
            )
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                manifest = _read_json(archive.read("manifest.json"))
                sections = {
                    name: _read_section(archive, path)
                    for name, path in FILES.items()
                    if path in archive.namelist()
                }
        except (
            OSError,
            RuntimeError,
            ValueError,
            zipfile.BadZipFile,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise InvalidInputError("Organization export archive could not be read.") from error
        return OrganizationArchive(
            manifest=manifest,
            sections=sections,
            verification=verification,
        )


def _read_json(content: bytes) -> dict[str, Any]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("JSON value must be an object.")
    return value


def _read_section(archive: zipfile.ZipFile, path: str) -> tuple[dict[str, Any], ...]:
    info = archive.getinfo(path)
    if info.file_size > MAX_MEMBER_BYTES:
        raise InvalidInputError(f"Organization export member is too large: {path}")
    content = archive.read(info)
    if path.endswith(".jsonl"):
        return tuple(_read_json(line) for line in content.splitlines())
    return (_read_json(content),)
