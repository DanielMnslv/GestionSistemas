"""Comando ``importar_antivirus_sheet``: importa el historial de renovaciones de antivirus (hoja RESPANTIV). No cambia los datos actuales del equipo. Es una simulación salvo con --confirmar.

Uso: ``python manage.py importar_antivirus_sheet`` (opciones en ``--help``).
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from inventario.google_sheet import (
    clave_placa,
    leer_hoja,
    libro_del_sheet,
    normalizar_placa,
    texto_celda,
)
from inventario.models import Equipo, RenovacionAntivirus

HOJA = "RESPANTIV"
COL_FECHA = "Marca temporal"
COL_PLACA = "elija placa de equipo a actualizar"
COL_ANTIVIRUS = "Escriba el antivirus que va a instalar"
COL_LICENCIA = "Escriba Licencia de Antivirus"
COL_VENCIMIENTO = "Ingresa fecha de vencimiento de antivirus"
ZONA = ZoneInfo("America/Bogota")


class Command(BaseCommand):
    """Importa el historial de renovaciones de antivirus (hoja RESPANTIV). No cambia los datos actuales del equipo. Es una simulación salvo con --confirmar."""
    help = (
        "Importa el historial de renovaciones de antivirus (hoja RESPANTIV). "
        "No cambia los datos actuales del equipo. Es una simulación salvo con "
        "--confirmar."
    )

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--archivo``: Ruta a un .xlsx del Sheet.
        - ``--confirmar``: Guardar los cambios.
        """
        parser.add_argument("--archivo", help="Ruta a un .xlsx del Sheet.")
        parser.add_argument("--confirmar", action="store_true", help="Guardar los cambios.")

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas.

        Sin ``--confirmar`` solo muestra lo que haría; no guarda nada.
        """
        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            filas = leer_hoja(
                archivo, HOJA,
                [COL_FECHA, COL_PLACA, COL_ANTIVIRUS, COL_LICENCIA, COL_VENCIMIENTO],
            )
        equipos = {e.placa: e for e in Equipo.objects.all()}
        por_clave = {}
        for e in equipos.values():
            por_clave.setdefault(clave_placa(e.placa), []).append(e)
        existentes = set(RenovacionAntivirus.objects.values_list("equipo_id", "fecha"))

        crear, omitidas = [], []
        for f in filas:
            placa = normalizar_placa(f[COL_PLACA])
            equipo = equipos.get(placa)
            if equipo is None:
                candidatos = por_clave.get(clave_placa(placa), [])
                equipo = candidatos[0] if len(candidatos) == 1 else None
            if equipo is None or not isinstance(f[COL_FECHA], datetime):
                omitidas.append(f"Fila {f['_fila']} ({placa}): equipo o fecha no encontrados.")
                continue
            fecha = timezone.make_aware(f[COL_FECHA].replace(microsecond=0), ZONA)
            if (equipo.pk, fecha) in existentes:
                continue
            existentes.add((equipo.pk, fecha))
            vence = f[COL_VENCIMIENTO]
            crear.append(RenovacionAntivirus(
                equipo=equipo, fecha=fecha,
                antivirus=texto_celda(f[COL_ANTIVIRUS])[:150] or "Sin dato",
                licencia=texto_celda(f[COL_LICENCIA])[:200],
                vencimiento=vence.date() if isinstance(vence, datetime) else (
                    vence if isinstance(vence, date) else None
                ),
                importada=True,
            ))

        self.stdout.write(f"Renovaciones a importar: {len(crear)}")
        for linea in omitidas:
            self.stdout.write(self.style.WARNING(f"  {linea}"))
        if not options["confirmar"]:
            self.stdout.write(self.style.WARNING(
                "SIMULACIÓN: no se guardó ningún cambio. Usa --confirmar para aplicar."
            ))
            return
        with transaction.atomic():
            RenovacionAntivirus.objects.bulk_create(crear)
        self.stdout.write(self.style.SUCCESS(f"Importación completada: {len(crear)} renovaciones."))
