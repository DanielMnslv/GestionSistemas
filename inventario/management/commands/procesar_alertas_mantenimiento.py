"""Comando ``procesar_alertas_mantenimiento``: revisa los mantenimientos que vencen hoy. Por defecto simula y no envía correos.

Uso: ``python manage.py procesar_alertas_mantenimiento`` (opciones en ``--help``).
"""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db.models import Q

from inventario.estado_mantenimiento import sumar_seis_meses
from inventario.notificaciones import destinatarios_alerta_equipo
from inventario.models import (
    AlertaMantenimiento,
    MantenimientoEquipo,
    Equipo,
)


ZONA_COLOMBIA = ZoneInfo("America/Bogota")


DESTINATARIO_PRUEBA = "d.jimenez@seguridadjano.com"
MAX_INTENTOS_ALERTA = 3
INTERVALO_REINTENTO_MINUTOS = 30



def fecha_base_intervencion(intervencion):
    """Fecha local (Colombia) de la intervención, desde la que se cuentan los 6 meses."""
    return timezone.localtime(
        intervencion.fecha_intervencion,
        ZONA_COLOMBIA,
    ).date()


def ubicacion(equipo):
    """Dónde está el equipo, según los datos disponibles de su tipo."""
    radio = getattr(equipo, "radio", None)
    if radio is not None:
        partes = [radio.cliente_asignado, radio.puesto_asignado]
        return " - ".join(p for p in partes if p) or "No registrada"
    return "No registrada"


class Command(BaseCommand):
    """Revisa los mantenimientos que vencen hoy. Por defecto simula y no envía correos."""
    help = (
        "Revisa los mantenimientos que vencen hoy. "
        "Por defecto simula y no envía correos."
    )

    
    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--enviar``: Envía las alertas que vencen hoy.
        - ``--probar-correo``: Envía un correo de prueba al destinatario configurado, sin crear alertas ni modificar registros.
        - ``--fecha-prueba``: Simula la revisión en una fecha específica, sin enviar correos ni crear alertas.
        """
        parser.add_argument(
            "--enviar",
            action="store_true",
            help="Envía las alertas que vencen hoy.",
        )
        
        parser.add_argument(
            "--probar-correo",
            action="store_true",
            help=(
                "Envía un correo de prueba al destinatario configurado, "
                "sin crear alertas ni modificar registros."
            ),
        )
    
        parser.add_argument(
            "--fecha-prueba",
            type=str,
            metavar="AAAA-MM-DD",
            help=(
                "Simula la revisión en una fecha específica, "
                "sin enviar correos ni crear alertas."
            ),
        )
    
    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas.

        Sin ``--enviar`` solo muestra lo que haría; no envía correos.
        """
        enviar = options["enviar"]
        probar_correo = options["probar_correo"]
        fecha_prueba = options.get("fecha_prueba")

        if probar_correo:
            if enviar or fecha_prueba:
                raise CommandError(
                    "--probar-correo no se puede combinar con "
                    "--enviar ni con --fecha-prueba."
                )

            if not settings.EMAIL_HOST_USER:
                raise CommandError(
                    "EMAIL_HOST_USER no está configurado."
                )

            try:
                cantidad = send_mail(
                    subject="Prueba de correo - JANO Inventario",
                    message=(
                        "Este es un correo de prueba del sistema "
                        "JANO Inventario.\n\n"
                        "No corresponde a un vencimiento real. "
                        "No se crearon alertas ni se modificaron "
                        "registros de mantenimiento."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[DESTINATARIO_PRUEBA],
                    fail_silently=False,
                )

                if cantidad != 1:
                    raise RuntimeError(
                        "El servidor no confirmó el envío del correo."
                    )

                self.stdout.write(
                    self.style.SUCCESS(
                        "Correo de prueba aceptado por SMTP para: "
                        f"{DESTINATARIO_PRUEBA}"
                    )
                )

            except Exception as exc:
                raise CommandError(
                    f"No se pudo enviar el correo de prueba: {exc}"
                ) from exc

            return


        if enviar and fecha_prueba:
            raise CommandError(
                "--fecha-prueba no se puede combinar con --enviar."
            )

        if fecha_prueba:
            try:
                hoy = date.fromisoformat(fecha_prueba)
            except ValueError:
                raise CommandError(
                    "Fecha inválida. Usa el formato AAAA-MM-DD."
                )
        else:
            hoy = timezone.now().astimezone(ZONA_COLOMBIA).date()

        self.stdout.write(f"Fecha de revisión: {hoy:%d/%m/%Y}")

        if enviar and not settings.EMAIL_HOST_USER:
            raise CommandError(
                "EMAIL_HOST_USER no está configurado. "
                "No se enviaron alertas."
            )

        equipos = (
            Equipo.objects.filter(activo=True)
            .select_related("radio")
            .order_by("tipo", "placa")
        )

        vencen_hoy = 0
        sin_historial = 0
        ya_enviadas = 0
        enviadas = 0
        errores = 0

        self.stdout.write(
            "MODO: " + ("ENVÍO REAL" if enviar else "SIMULACIÓN")
        )
        self.stdout.write("-" * 75)

        for equipo in equipos:
            ultima = MantenimientoEquipo.objects.filter(
                equipo=equipo
            ).order_by("-fecha_intervencion", "-id").first()

            # No inventar una intervención para equipos sin historial.
            if ultima is None:
                sin_historial += 1
                continue

            fecha_base = fecha_base_intervencion(ultima)
            vencimiento = sumar_seis_meses(fecha_base)

            
            # Recuperar solo alertas antiguas que todavía puedan reintentarse.
            # Las alertas agotadas o dentro del periodo de espera no bloquean
            # la alerta correspondiente al vencimiento de hoy.
            ahora_seleccion = timezone.now()
            limite_reintento = ahora_seleccion - timedelta(
                minutes=INTERVALO_REINTENTO_MINUTOS
            )

            alerta_antigua_pendiente = None

            # Priorizar alertas antiguas ya existentes que puedan reintentarse.
            # No crear alertas retroactivas.
            alerta_antigua_pendiente = (
                AlertaMantenimiento.objects.filter(
                    equipo=equipo,
                    fecha_vencimiento__lt=hoy,
                    estado__in=[
                        AlertaMantenimiento.Estado.PENDIENTE,
                        AlertaMantenimiento.Estado.ERROR,
                    ],
                    intentos__lt=MAX_INTENTOS_ALERTA,
                )
                .filter(
                    Q(ultimo_intento__isnull=True)
                    | Q(ultimo_intento__lte=limite_reintento)
                )
                .order_by("fecha_vencimiento", "id")
                .first()
            )

            alerta_existente = alerta_antigua_pendiente

            if alerta_existente is None:
                alerta_existente = (
                    AlertaMantenimiento.objects.filter(
                        equipo=equipo,
                        fecha_vencimiento=vencimiento,
                    ).first()
                )

            recuperar_antigua = (
                alerta_existente is not None
                and alerta_existente.fecha_vencimiento < hoy
                and alerta_existente.estado in (
                    AlertaMantenimiento.Estado.PENDIENTE,
                    AlertaMantenimiento.Estado.ERROR,
                )
            )

            if recuperar_antigua:
                pass
            elif vencimiento == hoy:
                vencen_hoy += 1
                self.stdout.write(
                    f"{equipo.placa} | "
                    f"Última intervención: {fecha_base:%d/%m/%Y} | "
                    f"Vencimiento: {vencimiento:%d/%m/%Y}"
                )
            else:
                # No crear alertas nuevas para vencimientos pasados.
                continue

            if recuperar_antigua and not enviar:
                continue
            if not enviar:
                continue

            if vencimiento == hoy and not recuperar_antigua:
                alerta, creada = AlertaMantenimiento.objects.get_or_create(
                    equipo=equipo,
                    fecha_vencimiento=vencimiento,
                    defaults={
                        "estado": AlertaMantenimiento.Estado.PENDIENTE,
                    },
                )
            else:
                alerta = alerta_existente

            if alerta.estado == AlertaMantenimiento.Estado.ENVIADA:
                ya_enviadas += 1
                self.stdout.write(
                    f"  Omitida: alerta ya enviada (ID {alerta.id})."
                )
                continue

            if alerta.intentos >= MAX_INTENTOS_ALERTA:
                self.stdout.write(
                    f"  Omitida: alcanzó el máximo de "
                    f"{MAX_INTENTOS_ALERTA} intentos (ID {alerta.id})."
                )
                continue

            ahora = timezone.now()
            if alerta.ultimo_intento is not None:
                proximo_intento = alerta.ultimo_intento + timedelta(
                    minutes=INTERVALO_REINTENTO_MINUTOS
                )
                if ahora < proximo_intento:
                    self.stdout.write(
                        f"  Omitida: debe esperar hasta "
                        f"{proximo_intento.astimezone(ZONA_COLOMBIA):%H:%M} "
                        f"(ID {alerta.id})."
                    )
                    continue

            alerta.intentos += 1
            alerta.ultimo_intento = ahora
            alerta.detalle_error = ""
            alerta.save(
                update_fields=[
                    "intentos",
                    "ultimo_intento",
                    "detalle_error",
                    "actualizada_en",
                ]
            )

            
            if recuperar_antigua:
                asunto = (
                    f"Alerta de mantenimiento pendiente - "
                    f"{equipo.get_tipo_display()} {equipo.placa}"
                )
                texto_vencimiento = (
                    "El sistema JANO Inventario informa que existe "
                    "una alerta de mantenimiento pendiente o fallida "
                    "cuyo vencimiento original ya pasó."
                )
                fecha_vencimiento_correo = alerta.fecha_vencimiento
                etiqueta_vencimiento = "Fecha de vencimiento original"
            else:
                asunto = (
                    f"Vencimiento de mantenimiento - "
                    f"{equipo.get_tipo_display()} {equipo.placa}"
                )
                texto_vencimiento = (
                    "El sistema JANO Inventario informa que hoy vence "
                    "el mantenimiento semestral del siguiente equipo."
                )
                fecha_vencimiento_correo = alerta.fecha_vencimiento
                etiqueta_vencimiento = "Fecha de vencimiento"

            mensaje = (
                "Buen día,\n\n"
                f"{texto_vencimiento}\n\n"
                f"Tipo: {equipo.get_tipo_display()}\n"
                f"Placa: {equipo.placa}\n"
                f"Marca: {equipo.marca or 'No registrada'}\n"
                f"Modelo: {equipo.modelo or 'No registrado'}\n"
                f"Serial: {equipo.serial or 'No registrado'}\n"
                f"Ubicación: {ubicacion(equipo)}\n"
                f"Última intervención: {fecha_base:%d/%m/%Y}\n"
                f"{etiqueta_vencimiento}: "
                f"{fecha_vencimiento_correo:%d/%m/%Y}\n\n"
                "Se solicita coordinar y registrar la intervención "
                "correspondiente en JANO Inventario.\n\n"
                "Mensaje automático del sistema JANO Inventario."
            )

            try:
                cantidad = send_mail(
                    subject=asunto,
                    message=mensaje,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=destinatarios_alerta_equipo(equipo),
                    fail_silently=False,
                )

                if cantidad != 1:
                    raise RuntimeError(
                        "El servidor no confirmó el envío del correo."
                    )

                alerta.estado = AlertaMantenimiento.Estado.ENVIADA
                alerta.enviada_en = timezone.now()
                alerta.detalle_error = ""
                alerta.save(
                    update_fields=[
                        "estado",
                        "enviada_en",
                        "detalle_error",
                        "actualizada_en",
                    ]
                )

                enviadas += 1
                self.stdout.write(
                    self.style.SUCCESS("  Correo aceptado por SMTP.")
                )

            except Exception as exc:
                alerta.estado = AlertaMantenimiento.Estado.ERROR
                alerta.detalle_error = str(exc)[:4000]
                alerta.save(
                    update_fields=[
                        "estado",
                        "detalle_error",
                        "actualizada_en",
                    ]
                )

                errores += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"  Error al enviar alerta ID {alerta.id}: {exc}"
                    )
                )

        self.stdout.write("-" * 75)
        self.stdout.write(f"Equipos revisados: {equipos.count()}")
        self.stdout.write(f"Sin historial: {sin_historial}")
        self.stdout.write(f"Vencen hoy: {vencen_hoy}")

        if enviar:
            self.stdout.write(f"Correos aceptados por SMTP: {enviadas}")
            self.stdout.write(f"Alertas ya enviadas y omitidas: {ya_enviadas}")
            self.stdout.write(f"Errores de envío: {errores}")
        else:
            self.stdout.write(
                "Simulación terminada. No se crearon alertas "
                "ni se enviaron correos."
            )

