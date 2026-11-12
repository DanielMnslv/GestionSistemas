from django.apps import AppConfig

class ApiIntegracionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api_integracion"

    def ready(self):
        from . import signals  # noqa: F401
