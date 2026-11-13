"""Datos comunes a todas las páginas: contadores del menú lateral."""
from django.core.cache import cache
from django.db import DatabaseError

CLAVE_MENU = "jano_menu_conteos"
SEGUNDOS_MENU = 120


def conteos_menu():
    """Mantenimientos vencidos y equipos por revisar (se guardan 2 minutos)."""
    datos = cache.get(CLAVE_MENU)
    if datos is None:
        from .estado_mantenimiento import VENCIDO, equipos_con_estado
        from .models import Equipo, RetiroFuncionario
        from .panel import _entregados

        activos = Equipo.objects.filter(activo=True)
        datos = {
            "equipos": activos.count(),
            "vencidos": sum(
                1 for e in equipos_con_estado(activos)
                if e.estado_mantenimiento == VENCIDO
            ),
            "revision": activos.filter(requiere_revision=True).count(),
        }
        try:
            datos["retiros"] = RetiroFuncionario.objects.filter(
                estado=RetiroFuncionario.Estado.EN_PROCESO
            ).count()
        except DatabaseError:
            # Base sin la migración del módulo de Usuarios: el resto del menú sigue.
            datos["retiros"] = 0
        datos["bodega"] = max(datos["equipos"] - _entregados(), 0)
        cache.set(CLAVE_MENU, datos, SEGUNDOS_MENU)
    return datos


def menu(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {"menu_conteos": conteos_menu()}
