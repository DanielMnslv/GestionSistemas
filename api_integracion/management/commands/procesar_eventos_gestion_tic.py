"""Comando ``procesar_eventos_gestion_tic``: procesa Inbox de Gestión TIC y actualiza proyecciones remotas de solo lectura.

Uso: ``python manage.py procesar_eventos_gestion_tic`` (opciones en ``--help``).
"""
import uuid

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api_integracion.models import IntegrationInbox, RegistroRemotoIntegrado


ENTIDADES_PERMITIDAS = {
    "actividad", "riesgo", "activo_critico", "validacion",
    "subactividad", "avance_subactividad", "tarea_calendario", "indicador",
}


class Command(BaseCommand):
    """Procesa Inbox de Gestión TIC y actualiza proyecciones remotas de solo lectura."""
    help = "Procesa Inbox de Gestión TIC y actualiza proyecciones remotas de solo lectura."

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--limit``
        - ``--retry-errors``
        """
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--retry-errors", action="store_true")

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas."""
        estados = ["RECIBIDO"]
        if options["retry_errors"]:
            estados.append("ERROR")
        pendientes = IntegrationInbox.objects.filter(
            sistema_origen="GESTION_TIC", estado__in=estados
        ).order_by("recibido_en")[:max(1, options["limit"])]

        procesados = errores = obsoletos = 0
        for evento in pendientes:
            try:
                with transaction.atomic():
                    fila = IntegrationInbox.objects.select_for_update().get(pk=evento.pk)
                    if fila.estado == "PROCESADO":
                        continue
                    tipo = fila.event_type
                    prefijo = "gestion_tic."
                    sufijo = ".upserted"
                    if not (tipo.startswith(prefijo) and tipo.endswith(sufijo)):
                        raise ValueError(f"Tipo de evento no permitido: {tipo}")
                    entidad = tipo[len(prefijo):-len(sufijo)]
                    if entidad not in ENTIDADES_PERMITIDAS:
                        raise ValueError(f"Entidad no habilitada para proyección: {entidad}")

                    public_id = uuid.UUID(str(fila.payload.get("public_id") or ""))
                    datos = fila.payload.get("data")
                    if not isinstance(datos, dict):
                        raise ValueError("El payload.data debe ser un objeto JSON.")

                    registro = RegistroRemotoIntegrado.objects.filter(
                        sistema_origen="GESTION_TIC",
                        entidad_origen=entidad,
                        public_id_origen=public_id,
                    ).first()

                    if registro and fila.ocurrido_en < registro.ocurrido_en:
                        obsoletos += 1
                    elif registro:
                        registro.aggregate_id_origen = fila.aggregate_id
                        registro.ultimo_event_id = fila.event_id
                        registro.ocurrido_en = fila.ocurrido_en
                        registro.datos = datos
                        registro.save(update_fields=[
                            "aggregate_id_origen", "ultimo_event_id",
                            "ocurrido_en", "datos", "actualizado_en",
                        ])
                    else:
                        RegistroRemotoIntegrado.objects.create(
                            sistema_origen="GESTION_TIC",
                            entidad_origen=entidad,
                            public_id_origen=public_id,
                            aggregate_id_origen=fila.aggregate_id,
                            ultimo_event_id=fila.event_id,
                            ocurrido_en=fila.ocurrido_en,
                            datos=datos,
                        )

                    fila.estado = "PROCESADO"
                    fila.procesado_en = timezone.now()
                    fila.error = ""
                    fila.save(update_fields=["estado", "procesado_en", "error"])
                    procesados += 1
            except Exception as exc:
                IntegrationInbox.objects.filter(pk=evento.pk).update(
                    estado="ERROR", error=str(exc)[:4000]
                )
                errores += 1

        self.stdout.write(self.style.SUCCESS(
            f"Procesados: {procesados}; obsoletos ignorados: {obsoletos}; errores: {errores}"
        ))
