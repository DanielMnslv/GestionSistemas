from rest_framework.permissions import BasePermission, SAFE_METHODS


class SoloLecturaIntegracion(BasePermission):
    """
    Permite exclusivamente consultas a través de la API.

    Métodos autorizados:
    GET, HEAD y OPTIONS.

    Métodos bloqueados:
    POST, PUT, PATCH y DELETE.
    """

    message = (
        "La integración con Gestión TIC tiene permisos "
        "exclusivamente de lectura."
    )

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS