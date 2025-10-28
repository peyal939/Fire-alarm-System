from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "realtime"

    def ready(self):
        # Intentionally left side-effect free so management commands/tests don't
        # touch MQTT or the database during app registry setup.
        # The MQTT worker is started from config.asgi when the ASGI server boots.
        return None
