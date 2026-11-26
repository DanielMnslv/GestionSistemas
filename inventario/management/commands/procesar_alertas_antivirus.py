"""Comando ``procesar_alertas_antivirus``: avisa por correo los antivirus vencidos o que vencen en los próximos días. Cada vencimiento se avisa una sola vez. Por defecto simula y no envía correos.

Uso: ``python manage.py procesar_alertas_antivirus`` (opciones en ``--help``).
"""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventario.models import AvisoAntivirus, DetalleComputador
from inventario.notificaciones import destinatarios_alerta_equipos


DIAS_ANTICIPACION = 30


class Command(BaseCommand):
    """Avisa por correo los antivirus vencidos o que vencen en los próximos días. Cada vencimiento se avisa una sola vez. Por defecto simula y no envía correos."""
    help = (
        "Avisa por correo los antivirus vencidos o que vencen en los "
        f"próximos {DIAS_ANTICIPACION} días. Cada vencimiento se avisa una "
        "sola vez. Por defecto simula y no envía correos."
    )

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--enviar``: Enviar el correo y registrar los avisos.
        """
        parser.add_argument(
            "--enviar", action="store_true",
            help="Enviar el correo y registrar los avisos.",
        )

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas.

        Sin ``--enviar`` solo muestra lo que haría; no envía correos.
        """
        enviar = options["enviar"]
        if enviar and not settings.EMAIL_HOST_USER:
            raise CommandError("EMAIL_HOST_USER no está configurado.")

        hoy = timezone.localdate()
        limite = hoy + timedelta(days=DIAS_ANTICIPACION)
        avisados = set(AvisoAntivirus.objects.values_list(
            "equipo_id", "fecha_vencimiento"
        ))
        pendientes = [
            d for d in DetalleComputador.objects.filter(
                equipo__activo=True, vencimiento_antivirus__lte=limite
            ).select_related("equipo").order_by("vencimiento_antivirus")
            if (d.equipo_id, d.vencimiento_antivirus) not in avisados
        ]

        self.stdout.write("MODO: " + ("ENVÍO REAL" if enviar else "SIMULACIÓN"))
        lineas = []
        for d in pendientes:
            estado = "VENCIDO" if d.vencimiento_antivirus < hoy else "por vencer"
            lineas.append(
                f"{d.equipo.placa} · {d.antivirus or 'Antivirus'} · vence "
                f"{d.vencimiento_antivirus:%d/%m/%Y} ({estado}) · "
                f"{d.equipo.responsable_nombre or 'sin responsable'}"
            )
        for linea in lineas:
            self.stdout.write(f"  {linea}")
        self.stdout.write(f"Antivirus por avisar: {len(pendientes)}")

        if not pendientes or not enviar:
            if not enviar:
                self.stdout.write("Simulación terminada. No se enviaron correos.")
            return

        mensaje = (
            "Buen día,\n\n"
            "El sistema JANO Inventario informa los siguientes antivirus "
            f"vencidos o que vencen en los próximos {DIAS_ANTICIPACION} "
            "días:\n\n" + "\n".join(f"- {l}" for l in lineas) +
            "\n\nSe solicita renovar las licencias y actualizar la fecha de "
            "vencimiento en la ficha de cada equipo.\n\n"
            "Mensaje automático del sistema JANO Inventario."
        )
        send_mail(
            subject=f"Antivirus por vencer: {len(pendientes)} equipo(s)",
            message=mensaje,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=destinatarios_alerta_equipos(
                d.equipo for d in pendientes
            ),
            fail_silently=False,
        )
        with transaction.atomic():
            AvisoAntivirus.objects.bulk_create([
                AvisoAntivirus(
                    equipo_id=d.equipo_id,
                    fecha_vencimiento=d.vencimiento_antivirus,
                )
                for d in pendientes
            ], ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS("Correo enviado y avisos registrados."))
