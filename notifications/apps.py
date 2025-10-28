from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        """Initialize Firebase Admin SDK when app starts."""
        from .firebase import initialize_firebase

        initialize_firebase()
