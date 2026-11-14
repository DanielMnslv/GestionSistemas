"""Comando ``generar_revision_fisica``: genera un Excel con los radios que necesitan revisión física: seriales repetidos o dudosos, radios sin inventario físico y registros del Sheet que no se pudieron cruzar.

Uso: ``python manage.py generar_revision_fisica`` (opciones en ``--help``).
"""
import re
from datetime import date
from pathlib import Path

import openpyxl
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Count
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from inventario.google_sheet import leer_hoja, libro_del_sheet, normalizar_serial
from inventario.management.commands import (
    importar_asignaciones_sheet,
    importar_mantenimientos_sheet,
    importar_radios_sheet,
)
from inventario.models import Equipo, Radio


ENCABEZADOS = [
    "Prioridad", "Problema", "Placa", "ID plataforma", "Serial registrado",
    "Detalle", "Qué verificar", "Resultado de la revisión", "Observaciones",
]
RESULTADOS = [
    "Confirmado como está",
    "Serial corregido",
    "Placa corregida",
    "Es el mismo radio que otro registro",
    "No se encontró el radio",
    "Dar de baja",
]
LINEA_OMITIDO = re.compile(r"Fila (\d+) \(([^)]*)\): (.*)")


class Command(BaseCommand):
    """Genera un Excel con los radios que necesitan revisión física: seriales repetidos o dudosos, radios sin inventario físico y registros del Sheet que no se pudieron cruzar."""
    help = (
        "Genera un Excel con los radios que necesitan revisión física: "
        "seriales repetidos o dudosos, radios sin inventario físico y "
        "registros del Sheet que no se pudieron cruzar."
    )

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--archivo``: Ruta a un .xlsx del Sheet.
        - ``--salida``: Ruta del Excel a generar (por defecto, en la carpeta del proyecto).
        """
        parser.add_argument("--archivo", help="Ruta a un .xlsx del Sheet.")
        parser.add_argument(
            "--salida",
            help="Ruta del Excel a generar (por defecto, en la carpeta "
                 "del proyecto).",
        )

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas."""
        salida = Path(
            options["salida"]
            or Path(settings.BASE_DIR)
            / f"revision_fisica_equipos_{date.today():%Y%m%d}.xlsx"
        )
        usuario = get_user_model()(username="revision")

        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            radios = importar_radios_sheet.Command()
            plan_radios = radios.planear([
                f for f in leer_hoja(
                    archivo, importar_radios_sheet.HOJA,
                    [importar_radios_sheet.COLUMNA_SERIAL,
                     *importar_radios_sheet.CAMPOS],
                )
                if f[importar_radios_sheet.COLUMNA_PLACA]
                or normalizar_serial(f[importar_radios_sheet.COLUMNA_SERIAL])
            ])
            asignaciones = importar_asignaciones_sheet.Command()
            plan_asignaciones = asignaciones.planear(leer_hoja(
                archivo, importar_asignaciones_sheet.HOJA, [
                    importar_asignaciones_sheet.COL_FECHA,
                    importar_asignaciones_sheet.COL_PLACA,
                    importar_asignaciones_sheet.COL_SERIAL,
                    importar_asignaciones_sheet.COL_PUESTO,
                    importar_asignaciones_sheet.COL_COORDINADOR,
                    importar_asignaciones_sheet.COL_CEDULA,
                    importar_asignaciones_sheet.COL_CLIENTE,
                    importar_asignaciones_sheet.COL_CLAUSULA,
                    importar_asignaciones_sheet.COL_FIRMA,
                    *importar_asignaciones_sheet.ESTADOS,
                ],
            ))
            mantenimientos = importar_mantenimientos_sheet.Command()
            plan_mantenimientos = mantenimientos.planear(leer_hoja(
                archivo, importar_mantenimientos_sheet.HOJA, [
                    importar_mantenimientos_sheet.COL_CODIGO,
                    importar_mantenimientos_sheet.COL_PLACA,
                    importar_mantenimientos_sheet.COL_RESPONSABLE,
                    importar_mantenimientos_sheet.COL_FECHA,
                    importar_mantenimientos_sheet.COL_ESPECIALISTA,
                    importar_mantenimientos_sheet.COL_TIPO,
                    importar_mantenimientos_sheet.COL_ACTIVIDAD,
                    importar_mantenimientos_sheet.COL_CAUSA,
                    importar_mantenimientos_sheet.COL_ESTADO,
                    importar_mantenimientos_sheet.COL_FALLA,
                ],
            ), usuario)

        filas = []
        filas += self.desde_omitidos(
            plan_radios["omitidos"], "BASEDATOS-RADIOS",
            "Ubicar el radio y leer el serial de la etiqueta.",
        )
        filas += self.desde_omitidos(
            plan_asignaciones["omitidos"], "RESPUESTA-RADIOS",
            "Confirmar a qué radio corresponde la entrega.",
        )
        for placa, (n, pista) in sorted(plan_mantenimientos["sin_equipo"].items()):
            detalle = f"{n} mantenimiento(s) en T.MANT sin equipo en la plataforma."
            if pista:
                detalle += (
                    f" El número coincide con el código físico de "
                    f"{pista.etiqueta} (placa {pista.placa or 'vacía'})."
                )
            filas.append([
                2, "Mantenimiento sin equipo", placa,
                pista.etiqueta if pista else "", pista.serial if pista else "",
                detalle, "Confirmar a qué radio pertenece esta placa.",
            ])

        repetidos = (
            Radio.objects.exclude(codigo_fisico="")
            .values("codigo_fisico").annotate(n=Count("id")).filter(n__gt=1)
        )
        for grupo in repetidos:
            for radio in Radio.objects.filter(
                codigo_fisico=grupo["codigo_fisico"]
            ):
                filas.append([
                    1, "Código físico repetido", radio.placa,
                    radio.etiqueta, radio.serial,
                    f"{grupo['n']} radios con el código "
                    f"{grupo['codigo_fisico']}.",
                    "Revisar la etiqueta física de cada radio.",
                ])

        # Equipos de TI (todo lo que no es radio).
        equipos = Equipo.objects.exclude(tipo=Equipo.Tipo.RADIO)
        por_serial = {}
        for equipo in equipos.exclude(serial=""):
            por_serial.setdefault(normalizar_serial(equipo.serial), []).append(equipo)
        for grupo in por_serial.values():
            if len(grupo) > 1:
                for equipo in grupo:
                    filas.append([
                        1, "Serial repetido entre equipos", equipo.placa,
                        equipo.get_tipo_display(), equipo.serial,
                        f"{len(grupo)} equipos con el mismo serial: "
                        + ", ".join(e.placa for e in grupo) + ".",
                        "Leer el serial de la etiqueta de cada equipo.",
                    ])
        for equipo in equipos.filter(
            activo=True, responsable_nombre="",
            tipo__in=[Equipo.Tipo.COMPUTADOR, Equipo.Tipo.TABLETA,
                      Equipo.Tipo.IMPRESORA, Equipo.Tipo.ESCANER],
        ):
            filas.append([
                2, "Equipo sin responsable", equipo.placa,
                equipo.get_tipo_display(), equipo.serial,
                "No tiene funcionario asignado en la plataforma.",
                "Confirmar quién lo tiene y registrar la entrega.",
            ])
        for equipo in equipos.filter(requiere_revision=True):
            filas.append([
                1, "Datos incompletos", equipo.placa,
                equipo.get_tipo_display(), equipo.serial,
                equipo.motivo_revision, "Completar el dato que falta.",
            ])

        for radio in Radio.objects.filter(requiere_revision=True):
            creado_desde_sheet = radio.motivo_revision.startswith("Creado desde")
            filas.append([
                3 if creado_desde_sheet else 1,
                "Sin inventario físico" if creado_desde_sheet
                else "Datos incompletos",
                radio.placa, radio.etiqueta, radio.serial,
                radio.motivo_revision,
                "Confirmar que el radio existe y anotar su código físico."
                if creado_desde_sheet else "Completar el dato que falta.",
            ])

        filas.sort(key=lambda f: (f[0], f[1], f[2]))
        self.escribir(salida, filas)
        self.stdout.write(
            self.style.SUCCESS(f"{len(filas)} registros para revisar: {salida}")
        )

    def desde_omitidos(self, lineas, hoja, verificar):
        """Convierte las líneas de "omitidos" de una importación en filas para revisar."""
        filas = []
        for linea in lineas:
            coincidencia = LINEA_OMITIDO.match(linea)
            fila, placa, motivo = (
                coincidencia.groups() if coincidencia else ("", "", linea)
            )
            if "repetido" in motivo:
                problema, prioridad = "Serial repetido en el Sheet", 1
            elif "parecido" in motivo:
                problema, prioridad = "Serial posiblemente mal digitado", 1
            elif "la placa es de" in motivo:
                problema, prioridad = "Placa y serial de radios distintos", 1
            else:
                problema, prioridad = "Registro sin cruzar", 2
            filas.append([
                prioridad, problema, placa, "", "",
                f"{hoja} fila {fila}: {motivo}", verificar,
            ])
        return filas

    def escribir(self, salida, filas):
        """Escribe el Excel de revisión física con formato y encabezados."""
        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = "Revisión"
        fuente = "Arial"

        hoja["A1"] = "Revisión física de radios – Seguridad Jano"
        hoja["A1"].font = Font(name=fuente, bold=True, size=14, color="1F3864")
        hoja["A2"] = (
            "Prioridad 1: datos contradictorios; 2: registros sin cruzar; "
            "3: radios del Sheet sin inventario físico. Diligenciar las "
            "columnas amarillas (Resultado y Observaciones)."
        )
        hoja["A2"].font = Font(name=fuente, italic=True, size=10, color="595959")

        for col, titulo in enumerate(ENCABEZADOS, 1):
            celda = hoja.cell(row=4, column=col, value=titulo)
            celda.font = Font(name=fuente, bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor="1F3864")
            celda.alignment = Alignment(wrap_text=True, vertical="center")

        amarillo = PatternFill("solid", fgColor="FFF2CC")
        for i, fila in enumerate(filas, 5):
            for col, valor in enumerate(fila + ["", ""], 1):
                celda = hoja.cell(row=i, column=col, value=valor)
                celda.font = Font(name=fuente, size=10)
                celda.alignment = Alignment(wrap_text=col in (6, 7), vertical="top")
                if col >= 8:
                    celda.fill = amarillo

        validacion = DataValidation(
            type="list", formula1='"' + ",".join(RESULTADOS) + '"',
            allow_blank=True,
        )
        hoja.add_data_validation(validacion)
        if filas:
            validacion.add(f"H5:H{4 + len(filas)}")

        anchos = [10, 30, 12, 14, 18, 60, 40, 28, 40]
        for col, ancho in enumerate(anchos, 1):
            hoja.column_dimensions[get_column_letter(col)].width = ancho
        hoja.freeze_panes = "A5"
        hoja.auto_filter.ref = f"A4:I{4 + max(len(filas), 1)}"
        libro.save(salida)
