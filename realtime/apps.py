from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "realtime"

    def ready(self):
        # Intentionally left side-effect free so management commands/tests don't
        # touch MQTT or the database during app registry setup.
        # The MQTT worker is started from config.asgi when the ASGI server boots.

        # Safety Check: Warn if running without Redis in a potentially multi-worker environment
        from django.conf import settings
        import logging

        logger = logging.getLogger(__name__)
        if (
            not getattr(settings, "CHANNEL_LAYERS", {})
            .get("default", {})
            .get("BACKEND", "")
            .endswith("RedisChannelLayer")
        ):
            logger.warning(
                "⚠️  RUNNING WITHOUT REDIS! "
                "You are using the in-memory channel layer. "
                "You MUST run Daphne with a single worker process (-p 8000), "
                "otherwise WebSocket clients will not receive updates from the MQTT worker."
            )

        return None
