from rest_framework.permissions import BasePermission
from inventario.permisos import ENCARGADO, TECNICO


class UsuarioJanoMovil(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or not user.is_active:
            return False
        roles = set(user.groups.values_list("name", flat=True))
        return bool(user.is_superuser or roles.intersection({ENCARGADO, TECNICO}))
