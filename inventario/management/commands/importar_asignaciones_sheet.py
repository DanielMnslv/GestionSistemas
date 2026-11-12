from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventario.google_sheet import (
    leer_hoja,
    libro_del_sheet,
    normalizar_encabezado,
    normalizar_placa,
    normalizar_serial,
    texto_celda,
)
from inventario.models import AsignacionRadio, Radio


HOJA = "RESPUESTA-RADIOS"
# Las marcas temporales del formulario están en hora de Colombia.
ZONA_FORMULARIO = ZoneInfo("America/Bogota")

COL_FECHA = "Marca temporal"
COL_PLACA = "Escriba Placa (RJ) del radio"
COL_SERIAL = "Escriba serial del Radio"
COL_PUESTO = "Nombre de Puesto"
COL_COORDINADOR = "Nombre y Apellidos  Completos del Coordinador de la Zona"
COL_CEDULA = "Cédula del Coordinador"
COL_CLIENTE = "Nombre de Cliente"
COL_CLAUSULA = "Clausula de Confidencialidad"
COL_FIRMA = "Adjunta Firma"
# Columna del formulario -> campo de AsignacionRadio.
ESTADOS = {
    "Estado del Radio": "estado_radio_entrega",
    "Estado de la Base": "estado_base_entrega",
    "Estado del Cargador": "estado_cargador_entrega",
    "Estado de la Antena": "estado_antena_entrega",
    "Estado de las Baterías": "estado_baterias_entrega",
}

PREFIJO = "[Formulario Google]"


def destino(entrega):
    """Lo que identifica una asignación: a quién y dónde se entregó."""
    return tuple(
        normalizar_encabezado(entrega[campo])
        for campo in (
            "cliente_asignado", "puesto_asignado", "cedula_funcionario"
        )
    )


class Command(BaseCommand):
    help = (
        "Importa el historial de entregas de radios desde la hoja "
        "RESPUESTA-RADIOS del Google Sheet. Cada respuesta del formulario "
        "es una entrega; la anterior del mismo radio se cierra como "
        "devuelta. Solo agrega respuestas posteriores a la última "
        "asignación registrada en la plataforma. Es una simulación salvo "
        "con --confirmar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--usuario",
            required=True,
            help="Usuario que figura como responsable de las entregas.",
        )
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
            help="Mostrar cada entrega que se registraría.",
        )

    def handle(self, *args, **options):
        try:
            usuario = get_user_model().objects.get(
                username=options["usuario"]
            )
        except get_user_model().DoesNotExist:
            raise CommandError(
                f"No existe el usuario {options['usuario']!r}."
            )

        columnas = [
            COL_FECHA, COL_PLACA, COL_SERIAL, COL_PUESTO, COL_COORDINADOR,
            COL_CEDULA, COL_CLIENTE, COL_CLAUSULA, COL_FIRMA, *ESTADOS,
        ]
        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            filas = leer_hoja(archivo, HOJA, columnas)

        plan = self.planear(filas)
        self.mostrar(plan, options["detalle"])

        if not options["confirmar"]:
            self.stdout.write(
                self.style.WARNING(
                    "SIMULACIÓN: no se guardó ningún cambio. "
                    "Usa --confirmar para aplicar."
                )
            )
            return

        with transaction.atomic():
            for radio, entregas in plan["radios"]:
                activa = AsignacionRadio.objects.filter(
                    radio=radio, estado=AsignacionRadio.Estado.ASIGNADO
                ).first()
                for entrega in entregas:
                    if activa:
                        self.cerrar(activa, entrega, usuario)
                    activa = AsignacionRadio.objects.create(
                        radio=radio,
                        entregado_por=usuario,
                        **{k: v for k, v in entrega.items()
                           if not k.startswith("_")},
                    )

        total = sum(len(e) for _, e in plan["radios"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Importación completada: {total} entregas en "
                f"{len(plan['radios'])} radios."
            )
        )

    def cerrar(self, asignacion, siguiente, usuario):
        asignacion.estado = AsignacionRadio.Estado.DEVUELTO
        asignacion.fecha_devolucion = siguiente["fecha_entrega"]
        asignacion.recibido_por = usuario
        asignacion.observaciones_devolucion = (
            f"{PREFIJO} Cerrada al registrarse una nueva entrega a "
            f"{siguiente['cliente_asignado']} - "
            f"{siguiente['puesto_asignado']}."
        )
        asignacion.save()

    def planear(self, filas):
        plan = {"radios": [], "omitidos": [], "sin_cambios": 0}

        radios = list(Radio.objects.all())
        por_placa = {
            normalizar_placa(r.placa): r for r in radios if r.placa
        }
        por_serial = {}
        for radio in radios:
            clave = normalizar_serial(radio.serial)
            if clave:
                por_serial.setdefault(clave, []).append(radio)

        entregas_por_radio = {}
        for fila in filas:
            etiqueta = f"Fila {fila['_fila']} ({texto_celda(fila[COL_PLACA])})"
            fecha = fila[COL_FECHA]
            if not isinstance(fecha, datetime):
                plan["omitidos"].append(f"{etiqueta}: sin marca temporal.")
                continue

            radio_placa = por_placa.get(normalizar_placa(fila[COL_PLACA]))
            candidatos = por_serial.get(normalizar_serial(fila[COL_SERIAL]), [])
            radio_serial = candidatos[0] if len(candidatos) == 1 else None
            if radio_placa and radio_serial and radio_placa != radio_serial:
                plan["omitidos"].append(
                    f"{etiqueta}: la placa es de {radio_placa.etiqueta} "
                    f"y el serial de {radio_serial.etiqueta}."
                )
                continue
            radio = radio_placa or radio_serial
            if not radio:
                plan["omitidos"].append(
                    f"{etiqueta}: no se encontró el radio por placa ni "
                    "por serial."
                )
                continue

            entregas_por_radio.setdefault(radio.pk, (radio, []))[1].append({
                "fecha_entrega": timezone.make_aware(
                    fecha.replace(microsecond=0), ZONA_FORMULARIO
                ),
                "coordinador_zona": texto_celda(fila[COL_COORDINADOR])[:200],
                "cedula_funcionario": texto_celda(fila[COL_CEDULA])[:50],
                "cliente_asignado": texto_celda(fila[COL_CLIENTE])[:200],
                "puesto_asignado": texto_celda(fila[COL_PUESTO])[:200],
                "observaciones_entrega": PREFIJO,
                **{
                    campo: texto_celda(fila[col])[:100]
                    for col, campo in ESTADOS.items()
                },
                "clausula_aceptada": (
                    texto_celda(fila[COL_CLAUSULA]).lower() in ("sí", "si")
                ),
                "enlace_firma": texto_celda(fila[COL_FIRMA])[:500],
                "_fila": fila["_fila"],
            })

        ultimas = {}
        for asignacion in AsignacionRadio.objects.order_by("fecha_entrega"):
            ultimas[asignacion.radio_id] = asignacion

        for radio, entregas in entregas_por_radio.values():
            entregas.sort(key=lambda e: e["fecha_entrega"])
            ultima = ultimas.get(radio.pk)
            if ultima:
                entregas = [
                    e for e in entregas
                    if e["fecha_entrega"] > ultima.fecha_entrega
                ]

            # Respuestas seguidas al mismo destino son la misma entrega
            # (reenvíos para corregir la firma, por ejemplo): se conserva
            # la fecha de la primera y los datos de la última.
            nuevas = []
            anterior = (
                destino(vars(ultima))
                if ultima and ultima.estado == AsignacionRadio.Estado.ASIGNADO
                else None
            )
            for entrega in entregas:
                if destino(entrega) == anterior:
                    if nuevas:
                        nuevas[-1] = {
                            **entrega,
                            "fecha_entrega": nuevas[-1]["fecha_entrega"],
                        }
                    continue
                nuevas.append(entrega)
                anterior = destino(entrega)

            if nuevas:
                plan["radios"].append((radio, nuevas))
            else:
                plan["sin_cambios"] += 1

        plan["radios"].sort(key=lambda par: par[0].placa)
        return plan

    def mostrar(self, plan, detalle):
        total = sum(len(e) for _, e in plan["radios"])
        self.stdout.write(
            f"Entregas a registrar: {total} en {len(plan['radios'])} radios"
        )
        self.stdout.write(f"Radios sin entregas nuevas: {plan['sin_cambios']}")
        self.stdout.write(f"Respuestas omitidas: {len(plan['omitidos'])}")

        if detalle:
            for radio, entregas in plan["radios"]:
                self.stdout.write(f"\n  {radio.etiqueta} ({radio.placa}):")
                for e in entregas:
                    self.stdout.write(
                        f"      {timezone.localtime(e['fecha_entrega'], ZONA_FORMULARIO):%Y-%m-%d %H:%M} "
                        f"{e['cliente_asignado']} - {e['puesto_asignado']} "
                        f"(coord. {e['coordinador_zona']})"
                    )

        if plan["omitidos"]:
            self.stdout.write("\nOmitidas (requieren revisión manual):")
            for linea in plan["omitidos"]:
                self.stdout.write(self.style.WARNING(f"  {linea}"))
