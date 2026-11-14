"""Registro de modelos en el administrador de Django (/admin/).

El trabajo diario se hace en las pantallas de la plataforma; el
administrador queda solo para soporte técnico.
"""

from django.contrib import admin
from .models import Radio


@admin.register(Radio)
class RadioAdmin(admin.ModelAdmin):
    """Radios en el administrador: columnas, filtros y búsqueda por placa o serial."""
    list_display = (
        "placa",
        "serial",
        "marca",
        "modelo",
        "estado_radio",
    )

    search_fields = (
        "codigo_fisico",
        "placa",
        "serial",
        "marca",
        "modelo",
        "cliente_asignado",
        "puesto_asignado",
    )

    list_filter = (
        "marca",
        "estado_radio",
        "mantenimiento",
    )
