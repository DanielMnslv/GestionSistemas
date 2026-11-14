"""Vistas de la API de integración con Gestión TIC.

Consultas (token): equipos, radios e indicadores, solo lectura y paginadas.
Recepción: eventos de Gestión TIC firmados con HMAC SHA256.
"""

import hashlib
import hmac
import json
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination

from .authentication import AutenticacionIntegracion
from .permissions import SoloLecturaIntegracion
from .serializers import (
    EquipoIntegracionSerializer,
    RadioIntegracionSerializer,
)
from .indicadores import periodo_desde_parametros, resumen_indicadores
from .models import IntegrationInbox, IntegrationAudit

from inventario.models import Equipo, Radio


class PaginacionIntegracion(PageNumberPagination):
    """Paginación de la API: 50 por página, máximo 100 con ``page_size``."""
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class BaseConsultaIntegracion(generics.ListAPIView):
    """Base de las consultas: exige token y solo permite lectura."""
    authentication_classes = [AutenticacionIntegracion]
    permission_classes = [
        IsAuthenticated,
        SoloLecturaIntegracion,
    ]
    pagination_class = PaginacionIntegracion


class EquiposAPI(BaseConsultaIntegracion):
    """Lista de equipos para Gestión TIC."""
    serializer_class = EquipoIntegracionSerializer

    def get_queryset(self):
        """Todos los equipos, ordenados por id."""
        return Equipo.objects.all().order_by("id")


class RadiosAPI(BaseConsultaIntegracion):
    """Lista de radios para Gestión TIC."""
    serializer_class = RadioIntegracionSerializer

    def get_queryset(self):
        """Todos los radios, ordenados por id."""
        return Radio.objects.all().order_by("id")


@csrf_exempt
@require_POST
def recibir_evento_gestion_tic(request):
    """
    Recibe eventos de Gestión TIC mediante firma HMAC SHA256.
    Almacena los eventos en Inbox sin modificar todavía
    los registros de negocio de JANO.
    """

    secreto = getattr(
        settings,
        "INTEGRACION_GESTION_TIC_SECRET",
        ""
    )

    if not secreto:
        return JsonResponse(
            {"detail": "Integración no configurada."},
            status=503
        )

    firma = request.headers.get(
        "X-GESTION-TIC-Signature",
        ""
    )

    firma_esperada = hmac.new(
        secreto.encode("utf-8"),
        request.body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(firma, firma_esperada):
        return JsonResponse(
            {"detail": "Firma no válida."},
            status=401
        )

    try:
        data = json.loads(request.body.decode("utf-8"))

        event_id = uuid.UUID(str(data["event_id"]))
        event_type = str(data["event_type"]).strip()
        payload = data.get("payload", {})
        ocurrido_en = parse_datetime(str(data.get("occurred_at", ""))) or timezone.now()
        if timezone.is_naive(ocurrido_en) and timezone.is_aware(timezone.now()):
            ocurrido_en = timezone.make_aware(ocurrido_en, timezone.get_current_timezone())

        if not event_type or not isinstance(payload, dict):
            raise ValueError(
                "event_type y payload válido son obligatorios."
            )

    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse(
            {"detail": "Formato de evento inválido."},
            status=400
        )

    evento, creado = IntegrationInbox.objects.get_or_create(
        sistema_origen="GESTION_TIC",
        event_id=event_id,
        defaults={
            "event_type": event_type,
            "aggregate_type": str(data.get("aggregate_type", ""))[:100],
            "aggregate_id": str(data.get("aggregate_id", ""))[:100],
            "payload": payload,
            "estado": "RECIBIDO",
            "ocurrido_en": ocurrido_en,
        }
    )

    IntegrationAudit.objects.create(
        sistema="GESTION_TIC",
        accion="EVENTO_RECIBIDO",
        entidad=str(data.get("aggregate_type", ""))[:100],
        referencia=str(event_id),
        resultado="OK" if creado else "DUPLICADO",
        detalle={
            "event_type": event_type,
            "aggregate_id": str(
                data.get("aggregate_id", "")
            ),
        }
    )

    return JsonResponse(
        {
            "accepted": True,
            "duplicate": not creado,
            "event_id": str(evento.event_id),
        },
        status=202
    )


class IndicadoresAPI(APIView):
    """GET /api/v1/indicadores/?desde=AAAA-MM-DD&hasta=AAAA-MM-DD

    Resumen de indicadores de JANO para Gestión TIC (mismo token de integración).
    Sin parámetros entrega el trimestre en curso.
    """

    authentication_classes = [AutenticacionIntegracion]
    permission_classes = [IsAuthenticated, SoloLecturaIntegracion]

    def get(self, request):
        """Devuelve los indicadores del período ``desde``/``hasta`` (por defecto, el trimestre).

        Responde 400 si las fechas no son válidas.
        """
        try:
            desde, hasta = periodo_desde_parametros(request.query_params)
        except (KeyError, ValueError):
            return Response(
                {"detail": "Use ?desde=AAAA-MM-DD&hasta=AAAA-MM-DD (máximo un año)."},
                status=400,
            )
        return Response(resumen_indicadores(desde, hasta))
