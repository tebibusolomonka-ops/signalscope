from fastapi import FastAPI

from signalscope.api.lifespan import lifespan
from signalscope.api.routes import health
from signalscope.core.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = load_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router)
    return app
