"""Comando ``validar_radios_excel``: valida el inventario Excel sin guardar ni modificar radios.

Uso: ``python manage.py validar_radios_excel``.
"""

from collections import Counter
from pathlib import Path

import openpyxl
from django.core.management.base import BaseCommand, CommandError

from inventario.models import Radio


ARCHIVO = Path(
    r"C:\Users\d.jimenez\Documents\JANO-Excel-Temporal"
    r"\inventario_radios_oficial_limpio.xlsx"
)

COLUMNAS_REQUERIDAS = [
    "ID Radio",
    "Marca",
    "Codigo",
    "S/N",
    "Batería 1",
    "Batería 2",
    "Perilla de Encendido",
    "Perilla de frecuencia",
    "Antena",
    "Clip",
    "Base",
    "Cargador",
    "Operativo",
    "Mantenimiento",
    "Notas / Observaciones",
]


class Command(BaseCommand):
    """Valida el inventario Excel sin guardar ni modificar radios."""
    help = "Valida el inventario Excel sin guardar ni modificar radios."

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas."""
        raise CommandError(
            "Este comando quedó obsoleto: el Excel antiguo identificaba los "
            "radios con un ID interno (RAD-xxx) que ya no existe. "
            "Los radios se identifican por su placa (RJ); usa "
            "importar_radios_sheet."
        )

        if not ARCHIVO.is_file():
            raise CommandError(
                f"No se encontró el archivo: {ARCHIVO}"
            )

        try:
            libro = openpyxl.load_workbook(
                ARCHIVO, read_only=True, data_only=True
            )
        except Exception as error:
            raise CommandError(
                f"No se pudo abrir el Excel: {error}"
            ) from error

        try:
            if "Inventario" not in libro.sheetnames:
                raise CommandError(
                    "El archivo no contiene la hoja Inventario."
                )

            hoja = libro["Inventario"]
            filas = hoja.iter_rows(values_only=True)
            encabezados = next(filas, None)

            if not encabezados:
                raise CommandError("La hoja está vacía.")

            encabezados = [
                str(valor).strip() if valor is not None else ""
                for valor in encabezados
            ]

            faltantes = [
                columna
                for columna in COLUMNAS_REQUERIDAS
                if columna not in encabezados
            ]

            if faltantes:
                raise CommandError(
                    "Faltan columnas requeridas: "
                    + ", ".join(faltantes)
                )

            indices = {
                nombre: encabezados.index(nombre)
                for nombre in COLUMNAS_REQUERIDAS
            }

            registros = []
            errores = []
            ids = []
            codigos = []
            seriales = []

            for numero_fila, valores in enumerate(filas, start=2):
                if not any(
                    valor is not None and str(valor).strip()
                    for valor in valores
                ):
                    continue

                def obtener(columna):
                    valor = valores[indices[columna]]
                    if valor is None:
                        return ""
                    return str(valor).strip()

                identificador = obtener("ID Radio")
                codigo = obtener("Codigo")
                serial = obtener("S/N")
                marca = obtener("Marca")

                if not identificador:
                    errores.append(
                        f"Fila {numero_fila}: falta ID Radio."
                    )
                    continue

                ids.append(identificador)

                if not codigo:
                    errores.append(
                        f"Fila {numero_fila} ({identificador}): "
                        "falta Codigo."
                    )

                if not serial:
                    errores.append(
                        f"Fila {numero_fila} ({identificador}): "
                        "falta S/N."
                    )

                if codigo:
                    codigos.append(codigo)

                if serial:
                    seriales.append(serial)

                registros.append({
                    "fila": numero_fila,
                    "id": identificador,
                    "codigo": codigo,
                    "serial": serial,
                    "marca": marca,
                })

            duplicados_excel = [
                identificador
                for identificador, cantidad in Counter(ids).items()
                if cantidad > 1
            ]

            existentes = set(
                Radio.objects.filter(
                    id_inventario__in=ids
                ).values_list("id_inventario", flat=True)
            )

            self.stdout.write(
                self.style.SUCCESS("VALIDACIÓN PREVIA DEL EXCEL")
            )
            self.stdout.write(f"Archivo: {ARCHIVO}")
            self.stdout.write(
                f"Radios con identificador: {len(registros)}"
            )
            self.stdout.write(
                f"ID Radio duplicados en Excel: "
                f"{len(duplicados_excel)}"
            )
            self.stdout.write(
                f"Códigos físicos repetidos: "
                f"{sum(c - 1 for c in Counter(codigos).values() if c > 1)}"
            )
            self.stdout.write(
                f"Seriales repetidos: "
                f"{sum(c - 1 for c in Counter(seriales).values() if c > 1)}"
            )
            self.stdout.write(
                f"ID Radio que ya existen en Django: {len(existentes)}"
            )
            self.stdout.write(
                f"Filas con datos faltantes: {len(errores)}"
            )

            for identificador in duplicados_excel:
                self.stdout.write(
                    self.style.ERROR(
                        f"ID duplicado en Excel: {identificador}"
                    )
                )

            for identificador in sorted(existentes):
                self.stdout.write(
                    self.style.WARNING(
                        f"Ya existe en la base de datos: {identificador}"
                    )
                )

            for error in errores:
                self.stdout.write(self.style.WARNING(error))

            self.stdout.write(
                self.style.WARNING(
                    "SIMULACIÓN COMPLETADA: no se guardó ni modificó "
                    "ningún radio."
                )
            )

        finally:
            libro.close()
