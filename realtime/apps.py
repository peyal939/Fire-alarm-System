from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "realtime"

    def ready(self):
        # Start MQTT background thread on app ready (only once)
        from .mqtt import ensure_mqtt_thread

        ensure_mqtt_thread()
