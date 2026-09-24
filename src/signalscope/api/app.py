from fastapi import FastAPI

from signalscope.core.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = load_settings()
    return FastAPI(title=settings.app_name, debug=settings.debug)
