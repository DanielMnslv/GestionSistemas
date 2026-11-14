"""Autenticación por token para las consultas de Gestión TIC a la API."""
from rest_framework.authentication import TokenAuthentication


class AutenticacionIntegracion(TokenAuthentication):
    """
    Autenticación mediante token exclusivo para integraciones.

    El token se envía mediante la cabecera:
    Authorization: Token <token>
    """

    keyword = "Token"