import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from realtime.routing import websocket_urlpatterns  # noqa: E402

# Serve static files when running under Daphne/ASGI in development
http_app = get_asgi_application()
if settings.DEBUG:
    http_app = ASGIStaticFilesHandler(http_app)

application = ProtocolTypeRouter(
    {
        "http": http_app,
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
