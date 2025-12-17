from django.apps import AppConfig


class ResellersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "resellers"
    verbose_name = "Reseller Management"

    def ready(self):
        # Import signals to register them
        import resellers.signals  # noqa: F401
