"""Registro de modelos en el administrador de Django (/admin/).

El trabajo diario se hace en las pantallas de la plataforma; el
administrador queda solo para soporte técnico.
"""

from django.contrib import admin
from .models import (
    AccesoPlataforma,
    ActivoInformacionSSI,
    CatalogoSSI,
    ControlSSIUsuario,
    Funcionario,
    PerfilPlataforma,
    PlataformaAcceso,
    Radio,
    Sede,
    VinculacionPersona,
)


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


@admin.register(Funcionario)
class FuncionarioAdmin(admin.ModelAdmin):
    list_display = ("cedula", "nombre_completo", "tipo_persona", "estado_persona", "cargo", "area")
    search_fields = ("cedula", "nombre_completo", "correo", "cargo", "area")
    list_filter = ("tipo_persona", "estado_persona", "activo")


@admin.register(Sede)
class SedeAdmin(admin.ModelAdmin):
    list_display = ("nombre", "cliente", "activo")
    search_fields = ("nombre", "cliente__nombre")
    list_filter = ("activo", "cliente")


@admin.register(VinculacionPersona)
class VinculacionPersonaAdmin(admin.ModelAdmin):
    list_display = ("funcionario", "cliente", "sede", "puesto", "cargo", "estado", "fecha_inicio", "fecha_fin")
    search_fields = ("funcionario__cedula", "funcionario__nombre_completo", "cliente__nombre", "puesto__nombre")
    list_filter = ("estado", "cliente", "sede")


@admin.register(PlataformaAcceso)
class PlataformaAccesoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo")
    search_fields = ("nombre", "descripcion")
    list_filter = ("activo",)


@admin.register(PerfilPlataforma)
class PerfilPlataformaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "plataforma", "activo")
    search_fields = ("nombre", "plataforma__nombre")
    list_filter = ("plataforma", "activo")


@admin.register(AccesoPlataforma)
class AccesoPlataformaAdmin(admin.ModelAdmin):
    list_display = ("funcionario", "plataforma", "usuario", "perfil_texto", "estado", "fuente", "fecha_asignacion", "fecha_revocacion")
    search_fields = ("funcionario__cedula", "funcionario__nombre_completo", "plataforma__nombre", "usuario", "perfil_texto")
    list_filter = ("estado", "plataforma", "fuente")
    readonly_fields = ("public_id", "creado_en", "actualizado_en")


@admin.register(ControlSSIUsuario)
class ControlSSIUsuarioAdmin(admin.ModelAdmin):
    list_display = ("funcionario", "proceso", "nivel_criticidad", "fecha_revision", "vpn", "usb")
    search_fields = ("funcionario__cedula", "funcionario__nombre_completo", "proceso")
    list_filter = ("nivel_criticidad", "vpn", "usb", "fecha_revision")


@admin.register(ActivoInformacionSSI)
class ActivoInformacionSSIAdmin(admin.ModelAdmin):
    list_display = ("activo", "proceso", "tipo_activo", "nivel_criticidad", "activo_registro")
    search_fields = ("activo", "proceso", "riesgos")
    list_filter = ("tipo_activo", "nivel_criticidad", "activo_registro")


@admin.register(CatalogoSSI)
class CatalogoSSIAdmin(admin.ModelAdmin):
    list_display = ("categoria", "valor", "activo")
    search_fields = ("categoria", "valor", "descripcion")
    list_filter = ("categoria", "activo")
