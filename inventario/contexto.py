"""Datos comunes a todas las páginas: contadores del menú lateral."""
from django.core.cache import cache

CLAVE_MENU = "jano_menu_conteos"
SEGUNDOS_MENU = 120


def conteos_menu():
    """Mantenimientos vencidos y equipos por revisar (se guardan 2 minutos)."""
    datos = cache.get(CLAVE_MENU)
    if datos is None:
        from .estado_mantenimiento import VENCIDO, equipos_con_estado
        from .models import Equipo

        activos = Equipo.objects.filter(activo=True)
        datos = {
            "equipos": activos.count(),
            "vencidos": sum(
                1 for e in equipos_con_estado(activos)
                if e.estado_mantenimiento == VENCIDO
            ),
            "revision": activos.filter(requiere_revision=True).count(),
        }
        cache.set(CLAVE_MENU, datos, SEGUNDOS_MENU)
    return datos


def menu(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {"menu_conteos": conteos_menu()}
