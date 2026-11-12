from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from inventario import tickets as flujo
from inventario.models import Ticket


class Command(BaseCommand):
    help = (
        f"Cierra los tickets resueltos hace más de "
        f"{flujo.DIAS_CIERRE_AUTOMATICO} días sin respuesta del solicitante. "
        "Es una simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--confirmar", action="store_true",
                            help="Cerrar los tickets.")

    def handle(self, *args, **options):
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
