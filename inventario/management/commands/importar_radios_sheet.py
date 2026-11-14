"""Comando ``importar_radios_sheet``: sincroniza radios desde la hoja BASEDATOS-RADIOS del Google Sheet: completa campos vacíos de los radios existentes (cruce por serial) y crea los que faltan. Es una simulación salvo con --confirmar.

Uso: ``python manage.py importar_radios_sheet`` (opciones en ``--help``).
"""
import re
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventario.google_sheet import (
    leer_hoja,
    libro_del_sheet,
    normalizar_serial,
    texto_celda,
)
from inventario.models import Radio


HOJA = "BASEDATOS-RADIOS"

COLUMNA_PLACA = "Placa"
COLUMNA_SERIAL = "Serial de equipo Radio"

# Columna del Sheet -> campo del modelo Radio.
CAMPOS = {
    "Placa": "placa",
    "Marca de Radio": "marca",
    "Modelo de  Radio": "modelo",
    "Tipo De Frecuencia": "tipo_frecuencia",
    "Modalidad de servicio": "modalidad_servicio",
    "Estado del Radio": "estado_radio",
    "Coordinador de Zona": "coordinador_zona",
    "Cedula Funcionario": "cedula_funcionario",
    "Cliente Asignado": "cliente_asignado",
    "Puesto Asignado": "puesto_asignado",
    "Estado de la Base": "estado_base",
    "Estado del Cargador": "estado_cargador",
    "Estado de  Antena": "estado_antena",
    "Estado de las Baterias": "estado_baterias",
    "Observaciones": "observaciones",
    "Software de Programación": "software_programacion",
    "Versión": "version_software",
    "Tipo de Licencia": "tipo_licencia",
    "Licencia de Software": "licencia_software",
    "Fecha de Compra": "fecha_compra",
}

MOTIVO_CREADO = (
    "Creado desde BASEDATOS-RADIOS; no figura en el inventario físico"
)


def distancia(a, b):
    """Distancia de edición (Levenshtein) entre dos textos.

    Se usa para detectar seriales casi iguales (un dígito mal escrito).
    """
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(
                anterior[j] + 1,
                actual[j - 1] + 1,
                anterior[j - 1] + (ca != cb),
            ))
        anterior = actual
    return anterior[-1]


def parecido_a_error_de_digitacion(a, b):
    """True si dos seriales parecen el mismo mal digitado.

    No cuenta un único carácter distinto: los seriales consecutivos de
    radios diferentes (…QHD / …QHT) se ven así.
    """
    if min(len(a), len(b)) < 6:
        return False
    if a in b or b in a:
        return True
    if len(a) == len(b):
        dif = [i for i in range(len(a)) if a[i] != b[i]]
        return (
            len(dif) == 2
            and dif[1] == dif[0] + 1
            and a[dif[0]] == b[dif[1]]
            and a[dif[1]] == b[dif[0]]
        )
    return abs(len(a) - len(b)) == 1 and distancia(a, b) == 1


def convertir(campo, valor):
    """Convierte una celda del Sheet al tipo del campo. None si vacía."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if campo == "fecha_compra":
        if isinstance(valor, datetime):
            return valor.date()
        if isinstance(valor, date):
            return valor
        for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(str(valor).strip(), formato).date()
            except ValueError:
                pass
        raise ValueError(f"fecha no reconocida {valor!r}")
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    if campo == "estado_radio":
        # "Bueno" del Sheet = "Operativo"; lo no reconocido se conserva.
        return Radio.normalizar_estado(texto) or texto
    if campo == "marca" and texto.isupper():
        # El inventario usa "Motorola", "Icom"…; el Sheet, mayúsculas.
        texto = texto.title()
    max_length = Radio._meta.get_field(campo).max_length
    if max_length and len(texto) > max_length:
        raise ValueError(f"supera {max_length} caracteres")
    return texto


class Command(BaseCommand):
    """Sincroniza radios desde la hoja BASEDATOS-RADIOS del Google Sheet: completa campos vacíos de los radios existentes (cruce por serial) y crea los que faltan. Es una simulación salvo con --confirmar."""
    help = (
        "Sincroniza radios desde la hoja BASEDATOS-RADIOS del Google Sheet: "
        "completa campos vacíos de los radios existentes (cruce por serial) "
        "y crea los que faltan. Es una simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--archivo``: Ruta a un .xlsx exportado del Google Sheet. Si se omite, se descarga el Sheet.
        - ``--confirmar``: Guardar los cambios después de validar todo.
        - ``--detalle``: Mostrar cada campo que se completaría.
        """
        parser.add_argument(
            "--archivo",
            help=(
                "Ruta a un .xlsx exportado del Google Sheet. Si se omite, "
                "se descarga el Sheet."
            ),
        )
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Guardar los cambios después de validar todo.",
        )
        parser.add_argument(
            "--detalle",
            action="store_true",
            help="Mostrar cada campo que se completaría.",
        )

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas.

        Sin ``--confirmar`` solo muestra lo que haría; no guarda nada.
        """
        confirmar = options["confirmar"]
        detalle = options["detalle"]

        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            filas = [
                fila for fila in leer_hoja(
                    archivo, HOJA, [COLUMNA_SERIAL, *CAMPOS]
                )
                if texto_celda(fila[COLUMNA_PLACA])
                or normalizar_serial(fila[COLUMNA_SERIAL])
            ]

        plan = self.planear(filas)

        self.mostrar(plan, detalle)

        if not confirmar:
            self.stdout.write(
                self.style.WARNING(
                    "SIMULACIÓN: no se guardó ningún cambio. "
                    "Usa --confirmar para aplicar."
                )
            )
            return

        with transaction.atomic():
            for radio, cambios in plan["actualizar"]:
                # Revalidar: solo se escriben campos que siguen vacíos.
                radio.refresh_from_db()
                vigentes = {
                    campo: valor for campo, valor in cambios.items()
                    if getattr(radio, campo) in (None, "")
                }
                for campo, valor in vigentes.items():
                    setattr(radio, campo, valor)
                if vigentes:
                    radio.save(update_fields=[*vigentes, "actualizado_en"])

            for datos in plan["crear"]:
                if Radio.objects.filter(placa__iexact=datos["placa"]).exists():
                    raise CommandError(
                        f"La placa {datos['placa']} ya existe. "
                        "Se canceló la importación."
                    )
                Radio.objects.create(**datos)

        self.stdout.write(
            self.style.SUCCESS(
                f"Importación completada: "
                f"{len(plan['actualizar'])} radios actualizados, "
                f"{len(plan['crear'])} radios creados."
            )
        )

    def planear(self, filas):
        """Calcula qué radios se crearían o completarían, sin guardar, y cuáles se omiten."""
        plan = {
            "actualizar": [],
            "crear": [],
            "omitidos": [],
            "avisos": [],
            "sin_cambios": 0,
        }

        radios = list(Radio.objects.all())
        por_serial = {}
        for radio in radios:
            clave = normalizar_serial(radio.serial)
            if clave:
                por_serial.setdefault(clave, []).append(radio)
        por_placa = {}
        for radio in radios:
            if radio.placa:
                por_placa.setdefault(radio.placa.strip().upper(), []).append(
                    radio
                )
        ids_existentes = {r.placa for r in radios if r.placa}

        conteo_seriales = {}
        for fila in filas:
            clave = normalizar_serial(fila[COLUMNA_SERIAL])
            if clave:
                conteo_seriales[clave] = conteo_seriales.get(clave, 0) + 1
        claves_sheet = set(conteo_seriales)
        # Seriales de la BD que no tienen par en el Sheet: candidatos a ser
        # el mismo radio con el serial mal digitado.
        huerfanos_bd = [c for c in por_serial if c not in claves_sheet]

        placas_reservadas = set(por_placa)

        for fila in filas:
            numero = fila["_fila"]
            placa = str(fila[COLUMNA_PLACA] or "").strip()
            etiqueta = f"Fila {numero} ({placa or 'sin placa'})"
            clave = normalizar_serial(fila[COLUMNA_SERIAL])

            valores = {}
            for columna, campo in CAMPOS.items():
                try:
                    valor = convertir(campo, fila[columna])
                except ValueError as error:
                    plan["avisos"].append(
                        f"{etiqueta}: {columna} se ignora ({error})."
                    )
                    continue
                if valor is not None:
                    valores[campo] = valor

            if clave and conteo_seriales[clave] > 1:
                plan["omitidos"].append(
                    f"{etiqueta}: serial {texto_celda(fila[COLUMNA_SERIAL])} "
                    "repetido "
                    "en el Sheet."
                )
                continue

            if clave:
                coincidencias = por_serial.get(clave, [])
            else:
                # Sin serial legible: solo se cruza por placa con un radio
                # de la BD que tampoco tenga serial.
                coincidencias = [
                    r for r in por_placa.get(placa.upper(), [])
                    if not normalizar_serial(r.serial)
                ]
                if not coincidencias:
                    plan["omitidos"].append(
                        f"{etiqueta}: sin serial y sin radio equivalente "
                        "por placa."
                    )
                    continue

            if len(coincidencias) > 1:
                plan["omitidos"].append(
                    f"{etiqueta}: el serial coincide con varios radios "
                    "de la BD ("
                    + ", ".join(r.etiqueta for r in coincidencias)
                    + ")."
                )
                continue

            if coincidencias:
                radio = coincidencias[0]
                cambios = {
                    campo: valor for campo, valor in valores.items()
                    if getattr(radio, campo) in (None, "")
                }
                if "placa" in cambios:
                    nueva = cambios["placa"].upper()
                    if nueva in placas_reservadas:
                        dueno = por_placa.get(nueva)
                        plan["avisos"].append(
                            f"{etiqueta}: no se asigna la placa a "
                            f"{radio.etiqueta}; ya la tiene "
                            + (dueno[0].etiqueta if dueno
                               else "otro radio de esta importación")
                            + "."
                        )
                        del cambios["placa"]
                    else:
                        placas_reservadas.add(nueva)
                if cambios:
                    plan["actualizar"].append((radio, cambios))
                else:
                    plan["sin_cambios"] += 1
                continue

            # No está en la BD: crear, salvo que haya dudas.
            parecidos = [
                c for c in huerfanos_bd
                if parecido_a_error_de_digitacion(clave, c)
            ]
            if parecidos:
                ids = ", ".join(
                    r.etiqueta for c in parecidos for r in por_serial[c]
                )
                plan["omitidos"].append(
                    f"{etiqueta}: serial {texto_celda(fila[COLUMNA_SERIAL])} "
                    "parecido "
                    f"al de {ids}; revisar si es el mismo radio."
                )
                continue
            if not placa:
                plan["omitidos"].append(
                    f"{etiqueta}: sin placa para usar como identificador."
                )
                continue
            if placa.upper() in placas_reservadas or placa in ids_existentes:
                plan["omitidos"].append(
                    f"{etiqueta}: la placa {placa} ya existe en la BD."
                )
                continue

            placas_reservadas.add(placa.upper())
            datos = {
                **valores,
                "placa": placa,
                "serial": texto_celda(fila[COLUMNA_SERIAL]),
                "requiere_revision": True,
                "motivo_revision": MOTIVO_CREADO,
            }
            plan["crear"].append(datos)

        return plan

    def mostrar(self, plan, detalle):
        """Imprime el resumen del plan (y el detalle si se pidió)."""
        campos_completados = sum(len(c) for _, c in plan["actualizar"])
        self.stdout.write(
            f"Radios a actualizar: {len(plan['actualizar'])} "
            f"({campos_completados} campos vacíos a completar)"
        )
        self.stdout.write(f"Radios sin cambios: {plan['sin_cambios']}")
        self.stdout.write(f"Radios a crear: {len(plan['crear'])}")
        self.stdout.write(f"Filas omitidas: {len(plan['omitidos'])}")

        if plan["actualizar"]:
            self.stdout.write("\nActualizaciones:")
            for radio, cambios in plan["actualizar"]:
                self.stdout.write(
                    f"  {radio.placa or 'sin placa'} (serial {radio.serial}): "
                    f"{len(cambios)} campos"
                )
                if detalle:
                    for campo, valor in cambios.items():
                        self.stdout.write(f"      {campo} = {valor}")

        if plan["crear"]:
            self.stdout.write("\nRadios nuevos:")
            for datos in plan["crear"]:
                self.stdout.write(
                    f"  {datos['placa']}: {datos.get('marca', '')} "
                    f"{datos.get('modelo', '')}, serial {datos['serial']}"
                )
                if detalle:
                    for campo, valor in datos.items():
                        self.stdout.write(f"      {campo} = {valor}")

        if plan["omitidos"]:
            self.stdout.write("\nOmitidos (requieren revisión manual):")
            for linea in plan["omitidos"]:
                self.stdout.write(self.style.WARNING(f"  {linea}"))

        if plan["avisos"]:
            self.stdout.write("\nAvisos:")
            for linea in plan["avisos"]:
                self.stdout.write(self.style.WARNING(f"  {linea}"))
