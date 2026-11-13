from django.contrib import admin
from .models import (
    EquivalenciaRegistro, IntegrationAudit, IntegrationDelivery,
    IntegrationInbox, IntegrationLink, IntegrationOutbox, RegistroRemotoIntegrado,
)

@admin.register(IntegrationOutbox)
class IntegrationOutboxAdmin(admin.ModelAdmin):
    list_display = ("event_type", "aggregate_type", "aggregate_id", "estado", "intentos", "creado_en")
    list_filter = ("estado", "event_type", "aggregate_type")
    search_fields = ("event_id", "aggregate_id", "idempotency_key")
    readonly_fields = [f.name for f in IntegrationOutbox._meta.fields]

@admin.register(IntegrationInbox)
class IntegrationInboxAdmin(admin.ModelAdmin):
    list_display = ("event_type", "sistema_origen", "estado", "recibido_en")
    list_filter = ("sistema_origen", "estado", "event_type")
    search_fields = ("event_id",)
    readonly_fields = [f.name for f in IntegrationInbox._meta.fields]

@admin.register(IntegrationLink)
class IntegrationLinkAdmin(admin.ModelAdmin):
    list_display = ("entidad", "objeto_local_id", "sistema_remoto", "estado")
    list_filter = ("sistema_remoto", "estado", "entidad")
    search_fields = ("objeto_local_id", "objeto_remoto_id")

@admin.register(IntegrationDelivery)
class IntegrationDeliveryAdmin(admin.ModelAdmin):
    list_display = ("destino", "codigo_http", "exito", "duracion_ms", "creado_en")
    list_filter = ("exito", "codigo_http")
    readonly_fields = [f.name for f in IntegrationDelivery._meta.fields]

@admin.register(IntegrationAudit)
class IntegrationAuditAdmin(admin.ModelAdmin):
    list_display = ("sistema", "accion", "entidad", "resultado", "creado_en")
    list_filter = ("sistema", "resultado", "accion")
    search_fields = ("referencia", "entidad")


@admin.register(RegistroRemotoIntegrado)
class RegistroRemotoIntegradoAdmin(admin.ModelAdmin):
    list_display = ("sistema_origen", "entidad_origen", "public_id_origen", "ocurrido_en")
    list_filter = ("sistema_origen", "entidad_origen")
    search_fields = ("public_id_origen", "aggregate_id_origen")
    readonly_fields = [f.name for f in RegistroRemotoIntegrado._meta.fields]


@admin.register(EquivalenciaRegistro)
class EquivalenciaRegistroAdmin(admin.ModelAdmin):
    list_display = ("entidad_local", "public_id_local", "entidad_remota",
                    "public_id_remoto", "estado", "sistema_remoto")
    list_filter = ("estado", "sistema_remoto", "entidad_local", "entidad_remota")
    search_fields = ("public_id_local", "public_id_remoto")
