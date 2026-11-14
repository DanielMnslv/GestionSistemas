"""Comando ``importar_radios_excel``: valida el Excel; solo importa con --confirmar.

Uso: ``python manage.py importar_radios_excel`` (opciones en ``--help``).
"""

from pathlib import Path

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventario.models import Radio


ARCHIVO = Path(
    r"C:\Users\d.jimenez\Documents\JANO-Excel-Temporal"
    r"\inventario_radios_oficial_limpio.xlsx"
)

COLUMNAS = [
    "ID Radio", "Marca", "Codigo", "S/N",
    "Batería 1", "Batería 2", "Perilla de Encendido",
    "Perilla de frecuencia", "Antena", "Clip", "Base",
    "Cargador", "Operativo", "Mantenimiento",
    "Notas / Observaciones",
]

ACCESORIOS = {
    "Batería 1": "bateria_1",
    "Batería 2": "bateria_2",
    "Perilla de Encendido": "perilla_encendido",
    "Perilla de frecuencia": "perilla_frecuencia",
    "Antena": "antena",
    "Clip": "clip",
    "Base": "base",
    "Cargador": "cargador",
}


class Command(BaseCommand):
    """Valida el Excel; solo importa con --confirmar."""
    help = "Valida el Excel; solo importa con --confirmar."

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--confirmar``: Guardar los radios después de validar todo.
        """
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Guardar los radios después de validar todo.",
        )

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas.

        Sin ``--confirmar`` solo muestra lo que haría; no guarda nada.
        """
        raise CommandError(
            "Este comando quedó obsoleto: el Excel antiguo identificaba los "
            "radios con un ID interno (RAD-xxx) que ya no existe. "
            "Los radios se identifican por su placa (RJ); usa "
            "importar_radios_sheet."
        )

        confirmar = options["confirmar"]

        if not ARCHIVO.is_file():
            raise CommandError(f"No se encontró el archivo: {ARCHIVO}")

        libro = openpyxl.load_workbook(
            ARCHIVO, read_only=True, data_only=True
        )

        try:
            if "Inventario" not in libro.sheetnames:
                raise CommandError("No existe la hoja Inventario.")

            hoja = libro["Inventario"]
            filas = hoja.iter_rows(values_only=True)
            encabezados = next(filas, None)

            if not encabezados:
                raise CommandError("La hoja está vacía.")

            encabezados = [
                str(v).strip() if v is not None else ""
                for v in encabezados
            ]

            faltantes = [c for c in COLUMNAS if c not in encabezados]
            if faltantes:
                raise CommandError(
                    "Faltan columnas: " + ", ".join(faltantes)
                )

            indices = {c: encabezados.index(c) for c in COLUMNAS}
            registros = []
            errores = []
            ids = []

            def texto(fila, columna):
                """Texto de una celda de la fila (sin ".0" en números enteros)."""
                valor = fila[indices[columna]]
                if valor is None:
                    return ""
                if isinstance(valor, float) and valor.is_integer():
                    return str(int(valor))
                return str(valor).strip()

            for numero, fila in enumerate(filas, start=2):
                if not any(
                    v is not None and str(v).strip() for v in fila
                ):
                    continue

                identificador = texto(fila, "ID Radio")
                if not identificador:
                    errores.append(f"Fila {numero}: falta ID Radio.")
                    continue

                ids.append(identificador)

                codigo = texto(fila, "Codigo")
                serial = texto(fila, "S/N")
                marca = texto(fila, "Marca")
                operativo = texto(fila, "Operativo").upper()
                mantenimiento = texto(fila, "Mantenimiento").upper()

                if operativo not in ("S", "N"):
                    errores.append(
                        f"Fila {numero} ({identificador}): "
                        f"Operativo inesperado: {operativo!r}"
                    )

                if mantenimiento not in ("", "S", "N"):
                    errores.append(
                        f"Fila {numero} ({identificador}): "
                        f"Mantenimiento inesperado: {mantenimiento!r}"
                    )

                datos = {
                    "id_inventario": identificador,
                    "codigo_fisico": codigo,
                    "serial": serial,
                    "marca": marca,
                    "estado_radio": (
                        "Operativo" if operativo == "S" else "Dañado"
                    ),
                    "mantenimiento": mantenimiento,
                    "observaciones": texto(
                        fila, "Notas / Observaciones"
                    ),
                }

                for columna, campo in ACCESORIOS.items():
                    valor = fila[indices[columna]]
                    if valor in (1, 1.0, True):
                        datos[campo] = True
                    elif valor in (0, 0.0, False):
                        datos[campo] = False
                    elif valor is None or str(valor).strip() == "":
                        datos[campo] = None
                    else:
                        errores.append(
                            f"Fila {numero} ({identificador}): "
                            f"{columna} tiene valor inesperado {valor!r}"
                        )

                motivos = []
                if not codigo:
                    motivos.append("Falta código físico")
                if not serial:
                    motivos.append("Falta serial")

                datos["requiere_revision"] = bool(motivos)
                datos["motivo_revision"] = "; ".join(motivos)
                registros.append(datos)

            if len(ids) != len(set(ids)):
                errores.append("Hay ID Radio duplicados en el Excel.")

            existentes = set(
                Radio.objects.filter(
                    id_inventario__in=ids
                ).values_list("id_inventario", flat=True)
            )
            if existentes:
                errores.append(
                    "Ya existen estos identificadores en Django: "
                    + ", ".join(sorted(existentes))
                )

            revisiones = [
                r for r in registros if r["requiere_revision"]
            ]

            self.stdout.write(f"Archivo: {ARCHIVO}")
            self.stdout.write(f"Radios leídos: {len(registros)}")
            self.stdout.write(
                f"Radios que requieren revisión: {len(revisiones)}"
            )
            self.stdout.write(
                f"Identificadores ya existentes: {len(existentes)}"
            )

            for radio in revisiones:
                self.stdout.write(
                    f"  {radio['id_inventario']}: "
                    f"{radio['motivo_revision']}"
                )

            if errores:
                for error in errores:
                    self.stderr.write(self.style.ERROR(error))
                raise CommandError(
                    "Validación fallida. No se guardó ningún radio."
                )

            if not confirmar:
                self.stdout.write(
                    self.style.WARNING(
                        "SIMULACIÓN: no se guardó ningún radio. "
                        "Revisa el resultado antes de importar."
                    )
                )
                return

            with transaction.atomic():
                # Revalidar identificadores justo antes de guardar.
                if Radio.objects.filter(
                    id_inventario__in=ids
                ).exists():
                    raise CommandError(
                        "Un identificador ya existe. "
                        "Se canceló la importación."
                    )

                for datos in registros:
                    Radio.objects.create(**datos)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Importación completada: {len(registros)} radios."
                )
            )

        finally:
            libro.close()
