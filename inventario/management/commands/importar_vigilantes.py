
from pathlib import Path

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventario.models import Vigilante


ARCHIVO = (
    Path(__file__).resolve().parents[3]
    / "importaciones"
    / "PREIMPORTACION_VIGILANTES.xlsx"
)

HOJA = "Vigilantes candidatos"

COLUMNAS = [
    "Hoja de origen",
    "Fila original",
    "Cédula",
    "Apellidos y nombres",
    "Estado de validación",
]


class Command(BaseCommand):
    help = (
        "Valida la preimportación de vigilantes. "
        "Solo guarda cambios con --confirmar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Guardar las altas y actualizaciones después de validar.",
        )

    def handle(self, *args, **options):
        confirmar = options["confirmar"]

        if not ARCHIVO.is_file():
            raise CommandError(f"No se encontró el archivo: {ARCHIVO}")

        libro = openpyxl.load_workbook(
            ARCHIVO, read_only=True, data_only=True
        )

        try:
            if HOJA not in libro.sheetnames:
                raise CommandError(f"No existe la hoja {HOJA!r}.")

            hoja = libro[HOJA]
            filas = hoja.iter_rows(values_only=True)
            encabezados = next(filas, None)

            if not encabezados:
                raise CommandError("La hoja está vacía.")

            encabezados = [
                str(valor).strip() if valor is not None else ""
                for valor in encabezados
            ]

            faltantes = [
                columna for columna in COLUMNAS
                if columna not in encabezados
            ]
            if faltantes:
                raise CommandError(
                    "Faltan columnas: " + ", ".join(faltantes)
                )

            indices = {
                columna: encabezados.index(columna)
                for columna in COLUMNAS
            }

            registros = []
            errores = []
            cedulas = []

            def valor_texto(fila, columna):
                indice = indices[columna]
                valor = fila[indice] if indice < len(fila) else None

                if valor is None:
                    return ""

                if isinstance(valor, bool):
                    return ""

                if isinstance(valor, float) and valor.is_integer():
                    return str(int(valor))

                return str(valor).strip()

            for numero_excel, fila in enumerate(filas, start=2):
                if not any(
                    valor is not None and str(valor).strip()
                    for valor in fila
                ):
                    continue

                origen = valor_texto(fila, "Hoja de origen")
                fila_origen_texto = valor_texto(fila, "Fila original")
                cedula = valor_texto(fila, "Cédula")
                nombre = valor_texto(fila, "Apellidos y nombres")
                estado = valor_texto(fila, "Estado de validación")

                if estado != "Pendiente de aprobación":
                    errores.append(
                        f"Fila {numero_excel}: estado inesperado "
                        f"{estado!r}; se esperaba 'Pendiente de aprobación'."
                    )
                    continue

                if not cedula or not cedula.isdigit():
                    errores.append(
                        f"Fila {numero_excel}: cédula vacía o inválida "
                        f"{cedula!r}."
                    )
                    continue

                if not nombre:
                    errores.append(
                        f"Fila {numero_excel} ({cedula}): falta el nombre."
                    )
                    continue

                if not origen:
                    errores.append(
                        f"Fila {numero_excel} ({cedula}): falta hoja de origen."
                    )
                    continue

                try:
                    fila_origen = int(fila_origen_texto)
                    if fila_origen < 1:
                        raise ValueError
                except (ValueError, TypeError):
                    errores.append(
                        f"Fila {numero_excel} ({cedula}): "
                        "fila original inválida."
                    )
                    continue

                cedulas.append(cedula)
                registros.append({
                    "cedula": cedula,
                    "nombre_completo": nombre,
                    "hoja_origen": origen,
                    "fila_origen": fila_origen,
                })

            if len(cedulas) != len(set(cedulas)):
                errores.append(
                    "El archivo contiene cédulas duplicadas."
                )

            existentes = {
                objeto.cedula: objeto
                for objeto in Vigilante.objects.filter(
                    cedula__in=cedulas
                )
            }

            altas = [
                registro for registro in registros
                if registro["cedula"] not in existentes
            ]

            actualizaciones = [
                registro for registro in registros
                if registro["cedula"] in existentes
            ]

            cambios_actualizacion = [
                registro for registro in actualizaciones
                if (
                    existentes[registro["cedula"]].nombre_completo
                    != registro["nombre_completo"]
                    or existentes[registro["cedula"]].hoja_origen
                    != registro["hoja_origen"]
                    or existentes[registro["cedula"]].fila_origen
                    != registro["fila_origen"]
                )
            ]

            self.stdout.write(f"Archivo: {ARCHIVO}")
            self.stdout.write(f"Filas válidas: {len(registros)}")
            self.stdout.write(f"Altas nuevas: {len(altas)}")
            self.stdout.write(
                f"Cédulas ya existentes: {len(actualizaciones)}"
            )
            self.stdout.write(
                f"Existentes con datos por actualizar: "
                f"{len(cambios_actualizacion)}"
            )
            self.stdout.write(f"Errores: {len(errores)}")

            for error in errores:
                self.stderr.write(self.style.ERROR(error))

            if errores:
                raise CommandError(
                    "Validación fallida. No se guardó ningún vigilante."
                )

            if not confirmar:
                self.stdout.write(
                    self.style.WARNING(
                        "SIMULACIÓN: no se guardó ningún vigilante. "
                        "Revise los resultados antes de confirmar."
                    )
                )
                return

            ahora = timezone.now()

            with transaction.atomic():
                # Revalidar dentro de la transacción antes de guardar.
                existentes_actuales = {
                    objeto.cedula: objeto
                    for objeto in Vigilante.objects.select_for_update().filter(
                        cedula__in=cedulas
                    )
                }

                for registro in registros:
                    datos = {
                        "nombre_completo": registro["nombre_completo"],
                        "hoja_origen": registro["hoja_origen"],
                        "fila_origen": registro["fila_origen"],
                        "ultima_actualizacion_excel": ahora,
                    }

                    objeto = existentes_actuales.get(registro["cedula"])

                    if objeto is None:
                        Vigilante.objects.create(
                            cedula=registro["cedula"],
                            **datos,
                        )
                    else:
                        for campo, valor in datos.items():
                            setattr(objeto, campo, valor)
                        objeto.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Importación completada: {len(altas)} altas y "
                    f"{len(actualizaciones)} registros existentes revisados."
                )
            )

        finally:
            libro.close()
