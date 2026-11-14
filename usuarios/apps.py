"""Configuración de la app ``usuarios`` (cuentas, ingreso y contraseñas)."""
from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    """Configuración de la app de usuarios."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usuarios'
