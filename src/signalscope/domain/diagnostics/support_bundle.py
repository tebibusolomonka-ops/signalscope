import hashlib
import importlib.metadata
import io
import json
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.deployment import DeploymentDiagnosticsService, DeploymentReport
from signalscope.domain.operations.queues import QUEUE_TABLES
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.storage.blob import BlobStore

BUNDLE_FORMAT_VERSION = "1"
MAX_RECENT_ERRORS = 50
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class SupportBundleService:
    """Build a safe support ZIP of read-only diagnostics.

    The bundle never contains passwords, tokens, the database URL, raw document
    or chunk text, research answers, model prompts or private assets. Operation
    errors are the short, people-facing messages that workers already store.
    """

    def __init__(self, settings: Settings, *, clock: Clock = utc_now) -> None:
        self.settings = settings
        self.clock = clock
        self.diagnostics = DeploymentDiagnosticsService(settings)

    async def build(self, session: AsyncSession, blobs: BlobStore | None) -> bytes:
        report = await self.diagnostics.collect(session, blobs)
        errors = await self._recent_errors(session)
        return self._zip(report, errors)

    def build_without_database(self) -> bytes:
        return self._zip(self.diagnostics.without_database(), [])

    def _zip(self, report: DeploymentReport, errors: list[dict[str, Any]]) -> bytes:
        data = report.to_dict()
        files = {
            "environment.json": _json(data["environment"]),
            "production_config.json": _json(data["production_config"]),
            "migration.json": _json(data["migration"]),
            "readiness.json": _json(data["readiness"]),
            "queues.json": _json(data["queues"]),
            "recent_errors.json": _json(errors),
            "version.txt": _version().encode("utf-8"),
        }
        manifest = {
            "format_version": BUNDLE_FORMAT_VERSION,
            "created_at": self.clock().isoformat(),
            "healthy": data["healthy"],
            "files": [
                {
                    "path": path,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
                for path, content in files.items()
            ],
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            _write(archive, "manifest.json", _json(manifest))
            for path, content in files.items():
                _write(archive, path, content)
        return output.getvalue()

    async def _recent_errors(self, session: AsyncSession) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for table in QUEUE_TABLES.values():
            model = table.model
            failed = table.status("failed")
            try:
                rows = await session.scalars(
                    select(model)
                    .where(model.status == failed, model.last_error.is_not(None))
                    .order_by(model.updated_at.desc())
                    .limit(MAX_RECENT_ERRORS)
                )
            except SQLAlchemyError:
                continue
            for row in rows:
                errors.append(
                    {
                        "queue": table.queue.value,
                        "message": row.last_error,
                        "finished_at": _iso(row.finished_at),
                    }
                )
        return errors


def _version() -> str:
    try:
        return importlib.metadata.version("signalscope")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write(archive: zipfile.ZipFile, path: str, content: bytes) -> None:
    info = zipfile.ZipInfo(path, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)
