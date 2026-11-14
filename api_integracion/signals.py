"""Publica un evento de salida cada vez que se guarda un equipo o un radio."""
import uuid
from django.db.models.signals import post_save
from django.dispatch import receiver

from inventario.models import Equipo, Radio
from .models import IntegrationOutbox


def _publicar(instancia, entidad, campos):
    """Crea el evento de salida con los ``campos`` del registro (fechas en ISO)."""
    datos = {}
    for campo in campos:
        valor = getattr(instancia, campo, None)
        if hasattr(valor, "isoformat"):
            valor = valor.isoformat()
        elif valor is not None:
            valor = str(valor) if campo in {"id", "public_id"} else valor
        datos[campo] = valor
    public_id = getattr(instancia, "public_id", None)
    event_id = uuid.uuid4()
    IntegrationOutbox.objects.create(
        event_id=event_id,
        event_type=f"jano.{entidad}.upserted",
        aggregate_type=entidad,
        aggregate_id=str(instancia.pk),
        payload={
            "public_id": str(public_id) if public_id else None,
            "local_id": str(instancia.pk),
            "data": datos,
        },
        idempotency_key=f"jano:{entidad}:{instancia.pk}:{event_id}",
    )


@receiver(post_save, sender=Equipo, dispatch_uid="jano_outbox_equipo_v1")
def equipo_guardado(sender, instance, created, **kwargs):
    """Señal post_save de Equipo: publica sus datos principales."""
    _publicar(instance, "equipo", [
        "id", "public_id", "placa", "tipo", "serial", "marca", "modelo",
        "propiedad", "fecha_compra", "estado_operativo", "activo",
    ])


@receiver(post_save, sender=Radio, dispatch_uid="jano_outbox_radio_v1")
def radio_guardado(sender, instance, created, **kwargs):
    """Señal post_save de Radio: publica sus datos principales."""
    _publicar(instance, "radio", [
        "id", "public_id", "codigo_fisico", "placa", "serial", "marca",
        "modelo", "tipo_frecuencia", "modalidad_servicio", "estado_radio",
        "activo", "fecha_baja",
    ])
