"""Comando ``inspeccionar_valores_excel``: inspecciona los valores del Excel sin modificar la base de datos.

Uso: ``python manage.py inspeccionar_valores_excel``.
"""

from pathlib import Path

import openpyxl
from django.core.management.base import BaseCommand, CommandError


ARCHIVO = Path(
    r"C:\Users\d.jimenez\Documents\JANO-Excel-Temporal"
    r"\inventario_radios_oficial_limpio.xlsx"
)


class Command(BaseCommand):
    """Inspecciona los valores del Excel sin modificar la base de datos."""
    help = "Inspecciona los valores del Excel sin modificar la base de datos."

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas."""
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

            columnas = [
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
                "CLIPS",
                "CANTIDAD",
            ]

            datos = list(filas)

            self.stdout.write(
                self.style.SUCCESS("VALORES ÚNICOS POR COLUMNA")
            )

            for nombre in columnas:
                if nombre not in encabezados:
                    self.stdout.write(
                        self.style.WARNING(
                            f"\n{nombre}: columna no encontrada"
                        )
                    )
                    continue

                indice = encabezados.index(nombre)
                valores = {}

                for fila in datos:
                    valor = fila[indice] if indice < len(fila) else None
                    etiqueta = (
                        "(vacío)"
                        if valor is None or str(valor).strip() == ""
                        else repr(valor)
                    )
                    valores[etiqueta] = valores.get(etiqueta, 0) + 1

                self.stdout.write(f"\n{nombre}:")
                for valor, cantidad in sorted(valores.items()):
                    self.stdout.write(f"  {valor}: {cantidad}")

            self.stdout.write(
                self.style.SUCCESS(
                    "\nInspección finalizada. No se modificó la base de datos."
                )
            )

        finally:
            libro.close()
