"""Comando ``simular_vencimientos_mantenimiento``: simula los vencimientos semestrales de mantenimiento sin modificar registros ni enviar correos.

Uso: ``python manage.py simular_vencimientos_mantenimiento``.
"""

from calendar import monthrange
from datetime import date
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone

from inventario.models import Radio


ZONA_COLOMBIA = ZoneInfo("America/Bogota")
FECHA_REFERENCIA = date(2026, 10, 16)


def sumar_seis_meses(fecha):
    """Suma seis meses a una fecha (si el día no existe, usa el último del mes)."""
    mes_total = fecha.month - 1 + 6
    anio = fecha.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(fecha.day, monthrange(anio, mes)[1])
    return date(anio, mes, dia)


class Command(BaseCommand):
    """Simula los vencimientos semestrales de mantenimiento sin modificar registros ni enviar correos."""
    help = (
        "Simula los vencimientos semestrales de mantenimiento "
        "sin modificar registros ni enviar correos."
    )

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas."""
        hoy = timezone.now().astimezone(ZONA_COLOMBIA).date()

        estados = {
            "al_dia": 0,
            "vencido": 0,
            "vence_hoy": 0,
        }
        sin_historial = 0

        self.stdout.write(f"Fecha de evaluación: {hoy}")
        self.stdout.write("MODO SIMULACIÓN: no se modifican datos.")
        self.stdout.write("-" * 100)

        for radio in Radio.objects.all().order_by("placa", "pk"):
            ultima = radio.mantenimientos.order_by(
                "-fecha_intervencion", "-id"
            ).first()

            if ultima:
                if ultima.origen_archivo:
                    fecha_base = ultima.fecha_intervencion.date()
                else:
                    fecha_base = timezone.localtime(
                        ultima.fecha_intervencion,
                        ZONA_COLOMBIA,
                    ).date()

                origen = "Historial"
            else:
                fecha_base = FECHA_REFERENCIA
                origen = "Referencia inicial"
                sin_historial += 1

            vencimiento = sumar_seis_meses(fecha_base)

            if vencimiento < hoy:
                estado = "VENCIDO"
                estados["vencido"] += 1
            elif vencimiento == hoy:
                estado = "VENCE HOY"
                estados["vence_hoy"] += 1
            else:
                estado = "AL DÍA"
                estados["al_dia"] += 1

            self.stdout.write(
                f"{radio.etiqueta} | "
                f"{origen} | "
                f"Base: {fecha_base:%d/%m/%Y} | "
                f"Vence: {vencimiento:%d/%m/%Y} | "
                f"{estado}"
            )

        self.stdout.write("-" * 100)
        self.stdout.write(f"Total de radios: {Radio.objects.count()}")
        self.stdout.write(f"Sin historial: {sin_historial}")
        self.stdout.write(f"Al día: {estados['al_dia']}")
        self.stdout.write(f"Vencidas: {estados['vencido']}")
        self.stdout.write(f"Vencen hoy: {estados['vence_hoy']}")
        self.stdout.write(
            self.style.SUCCESS(
                "Simulación finalizada. No se enviaron correos."
            )
        )
