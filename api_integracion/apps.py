"""Configuración de la app ``api_integracion``."""
from django.apps import AppConfig

class ApiIntegracionConfig(AppConfig):
    """Configuración de la app de integración con Gestión TIC."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "api_integracion"

    def ready(self):
        """Conecta las señales que publican eventos al guardar equipos y radios."""
        from . import signals  # noqa: F401
