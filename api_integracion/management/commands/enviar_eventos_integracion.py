import hashlib
import hmac
import json
import time
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from api_integracion.models import IntegrationOutbox, IntegrationDelivery


class Command(BaseCommand):
    help = "Entrega eventos pendientes de JANO a Gestión TIC."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--timeout", type=int, default=15)

    def handle(self, *args, **opts):
        url = getattr(settings, "INTEGRACION_GESTION_TIC_URL", "")
        secret = getattr(settings, "INTEGRACION_GESTION_TIC_SECRET", "")
        if not url or not secret:
            self.stderr.write("Configura INTEGRACION_GESTION_TIC_URL y el secreto HMAC.")
            return
        ahora = timezone.now()
        pendientes = IntegrationOutbox.objects.filter(estado="PENDIENTE").filter(
            proximo_intento__isnull=True
        ) | IntegrationOutbox.objects.filter(estado="PENDIENTE", proximo_intento__lte=ahora)
        total = 0
        for evento in pendientes.order_by("creado_en")[:max(1, opts["limit"])]:
            cuerpo = json.dumps({
                "event_id": str(evento.event_id),
                "event_type": evento.event_type,
                "aggregate_type": evento.aggregate_type,
                "aggregate_id": evento.aggregate_id,
                "payload": evento.payload,
                "occurred_at": evento.creado_en.isoformat(),
            }, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
            firma = hmac.new(secret.encode(), cuerpo, hashlib.sha256).hexdigest()
            req = Request(url, data=cuerpo, headers={
                "Content-Type": "application/json",
                "X-JANO-Signature": firma,
                "Idempotency-Key": evento.idempotency_key,
            }, method="POST")
            inicio = time.monotonic()
            codigo, respuesta, error = None, {}, ""
            try:
                with urlopen(req, timeout=max(1, opts["timeout"])) as resp:
                    codigo = resp.status
                    respuesta = json.loads(resp.read().decode("utf-8") or "{}")
                exito = 200 <= codigo < 300
            except HTTPError as exc:
                codigo = exc.code
                try:
                    respuesta = json.loads(exc.read().decode("utf-8") or "{}")
                except Exception:
                    respuesta = {}
                error = f"HTTP {codigo}"
                exito = False
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                error = str(exc)[:2000]
                exito = False
            duracion = int((time.monotonic() - inicio) * 1000)
            IntegrationDelivery.objects.create(
                outbox=evento, destino=url, codigo_http=codigo,
                respuesta=respuesta, exito=exito, duracion_ms=duracion,
            )
            evento.intentos += 1
            if exito:
                evento.estado = "ENVIADO"
                evento.enviado_en = timezone.now()
                evento.ultimo_error = ""
            else:
                evento.ultimo_error = error or f"HTTP {codigo}"
                evento.estado = "PENDIENTE" if evento.intentos < 10 else "ERROR"
                evento.proximo_intento = timezone.now() + timedelta(
                    seconds=min(3600, 30 * (2 ** min(evento.intentos - 1, 7)))
                )
            evento.save(update_fields=[
                "intentos", "estado", "enviado_en", "ultimo_error", "proximo_intento"
            ])
            total += 1
        self.stdout.write(f"Eventos procesados: {total}")
