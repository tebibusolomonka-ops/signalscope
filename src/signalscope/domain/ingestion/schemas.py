import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from signalscope.domain.ingestion.model import IngestionStatus


class IngestionRunCreate(BaseModel):
    # Status, times and errors are set by SignalScope, never by the client.
    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID


class IngestionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    status: IngestionStatus
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
