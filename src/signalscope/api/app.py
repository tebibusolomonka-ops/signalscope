from fastapi import FastAPI

from signalscope.api.errors import add_error_handlers
from signalscope.api.lifespan import lifespan
from signalscope.api.middleware import RequestIDMiddleware, RequestLoggingMiddleware
from signalscope.api.routes import (
    admin_users,
    auth,
    claims,
    dashboard,
    documents,
    embeddings,
    entities,
    event_clusters,
    events,
    health,
    ingestion_runs,
    investigation_members,
    investigations,
    organization_invitations,
    organizations,
    research,
    search,
    sources,
    timeline,
)
from signalscope.core.settings import Settings, load_settings
from signalscope.domain.users.passwords import PasswordHasher
from signalscope.embeddings.runtime import create_embedding_registry
from signalscope.entities.runtime import create_entity_extractor_registry
from signalscope.reranking.runtime import create_reranker_registry
from signalscope.research.runtime import create_answer_generator_registry


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = load_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.state.settings = settings
    # Empty unless local embeddings are enabled. Then semantic search answers 503.
    # Making the registry does not load the model.
    app.state.embedding_providers = create_embedding_registry(settings)
    # Empty unless local reranking is enabled. The model is not loaded here either.
    app.state.rerankers = create_reranker_registry(settings)
    # Empty unless local entity extraction is enabled. Nothing is loaded here.
    app.state.entity_extractors = create_entity_extractor_registry(settings)
    # Empty unless local answers are enabled. Then /research/answer answers 503.
    # The model is not loaded here either.
    app.state.answer_generators = create_answer_generator_registry(settings)
    # Argon2id with the library defaults. Tests put a cheaper one here.
    app.state.password_hasher = PasswordHasher()
    add_error_handlers(app)
    # The last middleware added runs first, so the request ID is set before logging.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin_users.router)
    app.include_router(organizations.router)
    app.include_router(organization_invitations.router)
    app.include_router(sources.router)
    app.include_router(documents.router)
    app.include_router(ingestion_runs.router)
    app.include_router(search.router)
    app.include_router(embeddings.router)
    app.include_router(entities.router)
    app.include_router(events.router)
    app.include_router(claims.router)
    app.include_router(timeline.router)
    app.include_router(event_clusters.router)
    app.include_router(research.router)
    app.include_router(investigations.router)
    app.include_router(investigation_members.router)
    app.include_router(dashboard.router)
    return app
