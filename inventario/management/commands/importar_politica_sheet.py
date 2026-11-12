from datetime import datetime
from zoneinfo import ZoneInfo

import openpyxl
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from inventario.google_sheet import (
    clave_placa,
    libro_del_sheet,
    normalizar_placa,
    texto_celda,
)
from inventario.models import Equipo, VerificacionPolitica
from inventario.politica import PUNTOS, normalizar_respuesta

HOJA = "VERIFICACION POLITICA"
ZONA = ZoneInfo("America/Bogota")
# Columnas por posición: los encabezados de los puntos son textos largos
# que varían en el Sheet. Los 15 puntos van de la columna 7 a la 21.
COL_FECHA, COL_PLACA, COL_FECHA_MANT, COL_ESPECIALISTA, COL_RESPONSABLE = 0, 1, 2, 3, 4
COL_PRIMER_PUNTO = 6
COL_OBSERVACIONES = COL_PRIMER_PUNTO + len(PUNTOS)
COL_ACTUALIZACION = COL_OBSERVACIONES + 1
VACIOS = {"", "NINGUNA", "N/A", "NA", "SIN NOVEDAD"}


class Command(BaseCommand):
    help = (
        "Importa las verificaciones de la política de seguridad de la hoja "
        "VERIFICACION POLITICA. Omite las ya importadas (mismo equipo y "
        "fecha). Es una simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        parser.add_argument("--archivo", help="Ruta a un .xlsx del Sheet.")
        parser.add_argument("--confirmar", action="store_true",
                            help="Guardar los cambios.")

    def handle(self, *args, **options):
        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            libro = openpyxl.load_workbook(archivo, read_only=True, data_only=True)
            try:
                filas = list(libro[HOJA].iter_rows(min_row=2, values_only=True))
            finally:
                libro.close()

        equipos = {e.placa: e for e in Equipo.objects.all()}
        por_clave = {}
        for e in equipos.values():
            por_clave.setdefault(clave_placa(e.placa), []).append(e)
        existentes = set(VerificacionPolitica.objects.values_list("equipo_id", "fecha"))

        crear, omitidas = [], []
        for numero, fila in enumerate(filas, start=2):
            if not any(fila):
                continue
            placa = normalizar_placa(fila[COL_PLACA])
            equipo = equipos.get(placa)
            if equipo is None:
                candidatos = por_clave.get(clave_placa(placa), [])
                equipo = candidatos[0] if len(candidatos) == 1 else None
            marca = fila[COL_FECHA]
            if equipo is None or not isinstance(marca, datetime):
                omitidas.append(f"Fila {numero} ({placa or 'sin placa'}): equipo o fecha no encontrados.")
                continue
            fecha = timezone.make_aware(marca.replace(microsecond=0), ZONA)
            if (equipo.pk, fecha) in existentes:
                continue
            existentes.add((equipo.pk, fecha))
            respuestas = {}
            for i, (clave, _) in enumerate(PUNTOS):
                valor = normalizar_respuesta(fila[COL_PRIMER_PUNTO + i])
                if valor:
                    respuestas[clave] = valor
            observaciones = texto_celda(fila[COL_OBSERVACIONES])
            crear.append(VerificacionPolitica(
                equipo=equipo,
                fecha=fecha,
                especialista=texto_celda(fila[COL_ESPECIALISTA])[:200],
                responsable=texto_celda(fila[COL_RESPONSABLE])[:200],
                respuestas=respuestas,
                observaciones="" if observaciones.upper() in VACIOS else observaciones,
                actualizacion=texto_celda(fila[COL_ACTUALIZACION]) if len(fila) > COL_ACTUALIZACION else "",
                importada=True,
            ))

        con_incumplimientos = sum(1 for v in crear if v.incumplimientos)
        self.stdout.write(f"Verificaciones a importar: {len(crear)}")
        self.stdout.write(f"  con incumplimientos: {con_incumplimientos}")
        self.stdout.write(f"Filas omitidas: {len(omitidas)}")
        for linea in omitidas:
            self.stdout.write(self.style.WARNING(f"  {linea}"))
        if not options["confirmar"]:
            self.stdout.write(self.style.WARNING(
                "SIMULACIÓN: no se guardó ningún cambio. Usa --confirmar para aplicar."
            ))
            return
        with transaction.atomic():
            VerificacionPolitica.objects.bulk_create(crear)
        self.stdout.write(self.style.SUCCESS(
            f"Importación completada: {len(crear)} verificaciones."
        ))
