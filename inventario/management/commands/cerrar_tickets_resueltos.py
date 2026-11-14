"""Comando ``cerrar_tickets_resueltos``: cierra los tickets resueltos hace más de 3 días sin respuesta del solicitante. Es una simulación salvo con --confirmar.

Uso: ``python manage.py cerrar_tickets_resueltos`` (opciones en ``--help``).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from inventario import tickets as flujo
from inventario.models import Ticket


class Command(BaseCommand):
    """Cierra los tickets resueltos hace más de 3 días sin respuesta del solicitante. Es una simulación salvo con --confirmar."""
    help = (
        f"Cierra los tickets resueltos hace más de "
        f"{flujo.DIAS_CIERRE_AUTOMATICO} días sin respuesta del solicitante. "
        "Es una simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--confirmar``: Cerrar los tickets.
        """
        parser.add_argument("--confirmar", action="store_true",
                            help="Cerrar los tickets.")

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas.

        Sin ``--confirmar`` solo muestra lo que haría; no guarda nada.
        """
        limite = timezone.now() - timedelta(days=flujo.DIAS_CIERRE_AUTOMATICO)
        pendientes = list(Ticket.objects.filter(
            estado=Ticket.Estado.RESUELTO, resuelto_en__lte=limite
        ).order_by("resuelto_en"))

        for ticket in pendientes:
            self.stdout.write(
                f"  {ticket.numero} · resuelto el "
                f"{timezone.localtime(ticket.resuelto_en):%d/%m/%Y}"
            )
            if options["confirmar"]:
                flujo.cerrar_automaticamente(ticket)
        self.stdout.write(
            f"Tickets {'cerrados' if options['confirmar'] else 'por cerrar'}: {len(pendientes)}"
        )
