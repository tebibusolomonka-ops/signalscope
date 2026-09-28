import io
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from event_reports import create_source
from signalscope.cli import export_investigation
from signalscope.core.exports import ExportFormat
from signalscope.core.settings import Settings
from signalscope.domain.investigations.item import InvestigationItemType
from signalscope.domain.investigations.service import InvestigationService

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    return Settings(database_url=migrated_database.database_url)


@pytest.fixture
async def investigation_id(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    source = await create_source(session_factory, "Wire")
    async with session_factory() as session:
        service = InvestigationService(session)
        investigation = await service.create("Harbour floods")
        await service.add_item(investigation.id, InvestigationItemType.SOURCE, source)
        return investigation.id


async def run(
    settings: Settings, investigation_id: uuid.UUID, **options: Any
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await export_investigation(investigation_id, settings, out, err, **options)
    return code, out.getvalue(), err.getvalue()


async def test_json_to_standard_output(settings: Settings, investigation_id: uuid.UUID) -> None:
    code, out, err = await run(settings, investigation_id)

    assert (code, err) == (0, "")
    data = json.loads(out)
    assert data["investigation"]["title"] == "Harbour floods"
    assert [item["snapshot"]["name"] for item in data["items"]] == ["Wire"]


async def test_markdown_to_standard_output(settings: Settings, investigation_id: uuid.UUID) -> None:
    code, out, _ = await run(settings, investigation_id, export_format=ExportFormat.MARKDOWN)

    assert code == 0
    assert out.startswith("# Harbour floods\n\nStatus: open\n\n## Sources\n\n- Wire (upload).")


async def test_file_output_and_overwrite(
    settings: Settings, investigation_id: uuid.UUID, tmp_path: Path
) -> None:
    path = tmp_path / "report.md"

    first = await run(settings, investigation_id, export_format=ExportFormat.MARKDOWN, output=path)
    again = await run(settings, investigation_id, output=path)
    replaced = await run(settings, investigation_id, output=path, overwrite=True)

    assert first == (0, f"Wrote {path}\n", "")
    assert again[0] == 1
    assert replaced[0] == 0
    assert json.loads(path.read_text(encoding="utf-8"))["investigation"]["title"] == (
        "Harbour floods"
    )


async def test_unknown_investigation(settings: Settings) -> None:
    code, out, err = await run(settings, uuid.uuid4())

    assert (code, out) == (1, "")
    assert err == "Error: Investigation was not found.\n"
