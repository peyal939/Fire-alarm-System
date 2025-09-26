from fastapi import FastAPI
from .core.config import get_settings
from .api import health as health_router
from .features.realtime import register_realtime


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

    # Routers
    app.include_router(health_router.router)

    # Mount realtime features (templates/static, WS, MQTT)
    register_realtime(app)

    return app


app = create_app()
