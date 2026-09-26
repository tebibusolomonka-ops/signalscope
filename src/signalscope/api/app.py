from fastapi import FastAPI

from signalscope.api.errors import add_error_handlers
from signalscope.api.lifespan import lifespan
from signalscope.api.middleware import RequestIDMiddleware, RequestLoggingMiddleware
from signalscope.api.routes import documents, embeddings, health, ingestion_runs, search, sources
from signalscope.core.settings import Settings, load_settings
from signalscope.embeddings.runtime import create_embedding_registry
from signalscope.reranking.runtime import create_reranker_registry


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
    add_error_handlers(app)
    # The last middleware added runs first, so the request ID is set before logging.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health.router)
    app.include_router(sources.router)
    app.include_router(documents.router)
    app.include_router(ingestion_runs.router)
    app.include_router(search.router)
    app.include_router(embeddings.router)
    return app
