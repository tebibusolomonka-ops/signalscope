import uuid

from fastapi import APIRouter

from signalscope.api.dependencies import DatabaseSessionFactory
from signalscope.api.tenancy import OrganizationFilter, Policy
from signalscope.domain.search.embedding_coverage import EmbeddingCoverageService
from signalscope.domain.search.schemas import EmbeddingCoverageRead
from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL

router = APIRouter(prefix="/embeddings", tags=["Embeddings"])


@router.get("/coverage")
async def embedding_coverage(
    session_factory: DatabaseSessionFactory,
    policy: Policy,
    organization_id: OrganizationFilter = None,
    document_id: uuid.UUID | None = None,
) -> EmbeddingCoverageRead:
    """Count the chunks that have a current embedding from the local E5 model.

    The numbers come from the database, so the model does not need to be
    installed or loaded. document_id limits them to one document. With
    authentication on, the counts cover the organization_id organization, or
    the document's organization when document_id is given.
    """
    spec = MULTILINGUAL_E5_SMALL
    service = EmbeddingCoverageService(session_factory)
    if document_id is None:
        scope = await policy.scope(organization_id)
        coverage = await service.overall(spec.provider, spec.model, scope)
    else:
        await policy.authorize_document(document_id)
        coverage = await service.for_document(document_id, spec.provider, spec.model)
    return EmbeddingCoverageRead(
        provider=spec.provider,
        model=spec.model,
        document_id=document_id,
        chunk_count=coverage.chunk_count,
        embedded_count=coverage.embedded_count,
        pending_count=coverage.pending_count,
        failed_count=coverage.failed_count,
        coverage=(coverage.embedded_count / coverage.chunk_count if coverage.chunk_count else None),
    )
