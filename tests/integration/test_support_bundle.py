import dataclasses
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.support_bundle import SupportBundleService
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.storage.local import LocalBlobStore
from tenancy_helpers import add_document, add_source

pytestmark = pytest.mark.anyio

TENANT_TEXT = "SENSITIVE_TENANT_SENTENCE_marker"
SAFE_ERROR = "embedding worker failed to reach the model"


async def test_bundle_has_no_secrets_or_tenant_content(
    migrated_database: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = dataclasses.replace(migrated_database, blob_dir=tmp_path / "blobs")
    source_id = await add_source(session_factory, None, "Bundle source")
    _, chunk_ids = await add_document(session_factory, source_id, "Bundle doc", [TENANT_TEXT])
    async with session_factory() as session:
        session.add(
            EmbeddingJob(
                chunk_id=chunk_ids[0],
                provider="test",
                model="m",
                status=EmbeddingJobStatus.FAILED,
                available_at=datetime.now(UTC),
                last_error=SAFE_ERROR,
                finished_at=datetime.now(UTC),
            )
        )
        await session.commit()

    blobs = LocalBlobStore(settings.blob_dir)
    async with session_factory() as session:
        data = await SupportBundleService(settings).build(session, blobs)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(contents["manifest.json"])
        recent_errors = json.loads(contents["recent_errors.json"])

    whole = b"".join(contents.values())
    # No tenant content and no database URL (which carries credentials).
    assert TENANT_TEXT.encode() not in whole
    assert settings.database_url is not None
    assert settings.database_url.encode() not in whole
    # The safe operation error is included.
    assert any(
        item["message"] == SAFE_ERROR and item["queue"] == "embedding" for item in recent_errors
    )
    # Checksums are correct.
    for entry in manifest["files"]:
        assert hashlib.sha256(contents[entry["path"]]).hexdigest() == entry["sha256"]
