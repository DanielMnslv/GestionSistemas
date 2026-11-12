"""Orden natural de placas: RJ-2 antes que RJ-10 y RJ-011 después de RJ-10."""
from django.db.models import IntegerField
from django.db.models.functions import Cast, Coalesce, Substr, Upper


def orden_placa(queryset, *antes, campo="placa", desempate=("pk",)):
    """Ordena por prefijo de letras y luego por el número de la placa."""
    return queryset.annotate(
        _placa_prefijo=Upper(Substr(campo, 1, 3)),
        _placa_numero=Coalesce(Cast(Substr(campo, 4), IntegerField()), 0),
    ).order_by(*antes, "_placa_prefijo", "_placa_numero", campo, *desempate)
