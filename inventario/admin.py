
from django.contrib import admin
from .models import Radio


@admin.register(Radio)
class RadioAdmin(admin.ModelAdmin):
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
