"""Comando ``importar_mantenimientos_sheet``: importa los mantenimientos de todos los equipos (radios, computadores, impresoras…) desde la hoja T.MANT del Google Sheet. Omite los que ya existen para el mismo equipo, día y tipo. Es una simulación salvo con --confirmar.

Uso: ``python manage.py importar_mantenimientos_sheet`` (opciones en ``--help``).
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventario.google_sheet import (
    leer_hoja,
    libro_del_sheet,
    normalizar_placa,
    clave_placa,
    texto_celda,
)
from inventario.models import Equipo, MantenimientoEquipo, Radio


HOJA = "T.MANT"
ORIGEN = "Google Sheet CONTROL DE MANTENIMIENTO DE EQUIPOS"
ZONA_COLOMBIA = ZoneInfo("America/Bogota")

COL_CODIGO = "CODIGO DE BUSQUEDA"
COL_PLACA = "PLACA EQUIPO"
COL_RESPONSABLE = "FUNCIONARIO RESPONSABLE DEL EQUIPO"
COL_FECHA = "FECHA DE MANTENIMIENTO"
COL_ESPECIALISTA = "ESPECIALISTA"
COL_TIPO = "QUE TIPO DE MANTENIMIENTO"
COL_ACTIVIDAD = "ACTIVIDAD REALIZADA"
COL_CAUSA = "CUAL PUDO SER LA CAUSA DEL DAÑO PRESENTADO"
COL_ESTADO = "ESTADO FINAL DEL EQUIPO"
COL_FALLA = "FALLA"

SIN_DATO = "No informado en el Sheet"


def obtener_tipo(valor):
    """Tipo de mantenimiento según el texto del Sheet (preventivo, correctivo…)."""
    texto = texto_celda(valor).upper()
    for palabra, tipo in (
        ("PREVENTIVO", MantenimientoEquipo.Tipo.PREVENTIVO),
        ("CORRECTIVO", MantenimientoEquipo.Tipo.CORRECTIVO),
        ("INSPECCION", MantenimientoEquipo.Tipo.INSPECCION),
        ("DIAGNOSTICO", MantenimientoEquipo.Tipo.DIAGNOSTICO),
        ("REPARACION", MantenimientoEquipo.Tipo.REPARACION),
        ("OTRO", MantenimientoEquipo.Tipo.OTRO),
    ):
        if palabra in texto:
            return tipo
    return None


def obtener_estado_final(valor):
    """Estado final del equipo según el texto del Sheet."""
    texto = texto_celda(valor).upper()
    if "NO SE REPARA" in texto or "BAJA" in texto or "NO OPERATIVO" in texto:
        return MantenimientoEquipo.EstadoFinal.NO_OPERATIVO
    if "TERCER NIVEL" in texto or "PRUEBA" in texto:
        return MantenimientoEquipo.EstadoFinal.PENDIENTE_PRUEBAS
    if "OPERATIVO" in texto:
        return MantenimientoEquipo.EstadoFinal.OPERATIVO
    return ""


def obtener_resultado(valor):
    """Resultado del mantenimiento (completo, parcial, pendiente) según el texto del Sheet."""
    texto = texto_celda(valor).upper()
    if "NO SE REPARA" in texto or "BAJA" in texto or "TERCER NIVEL" in texto:
        return MantenimientoEquipo.Resultado.PENDIENTE
    if "PARCIAL" in texto:
        return MantenimientoEquipo.Resultado.PARCIAL
    if "OPERATIVO" in texto and "NO OPERATIVO" not in texto:
        return MantenimientoEquipo.Resultado.SOLUCIONADO
    return MantenimientoEquipo.Resultado.PENDIENTE


def fecha_local(valor):
    """Convierte el valor de la celda en fecha, o None si no se puede."""
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, date):
        return valor
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto_celda(valor), formato).date()
        except ValueError:
            pass
    return None


class Command(BaseCommand):
    """Importa los mantenimientos de todos los equipos (radios, computadores, impresoras…) desde la hoja T.MANT del Google Sheet. Omite los que ya existen para el mismo equipo, día y tipo. Es una simulación salvo con --confirmar."""
    help = (
        "Importa los mantenimientos de todos los equipos (radios, "
        "computadores, impresoras…) desde la hoja T.MANT del Google Sheet. "
        "Omite los que ya existen para el mismo equipo, día y tipo. Es una "
        "simulación salvo con --confirmar."
    )

    def add_arguments(self, parser):
        """Opciones del comando:

        - ``--usuario``: Usuario que figura como quien registró las intervenciones.
        - ``--archivo``: Ruta a un .xlsx exportado del Google Sheet. Si se omite, se descarga el Sheet.
        - ``--confirmar``: Guardar los cambios después de validar todo.
        """
        parser.add_argument(
            "--usuario",
            required=True,
            help="Usuario que figura como quien registró las intervenciones.",
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

    def handle(self, *args, **options):
        """Ejecuta el comando con las opciones recibidas.

        Sin ``--confirmar`` solo muestra lo que haría; no guarda nada.
        """
        try:
            usuario = get_user_model().objects.get(
                username=options["usuario"]
            )
        except get_user_model().DoesNotExist:
            raise CommandError(
                f"No existe el usuario {options['usuario']!r}."
            )

        columnas = [
            COL_CODIGO, COL_PLACA, COL_RESPONSABLE, COL_FECHA,
            COL_ESPECIALISTA, COL_TIPO, COL_ACTIVIDAD, COL_CAUSA,
            COL_ESTADO, COL_FALLA,
        ]
        with libro_del_sheet(options["archivo"], self.stdout) as archivo:
            filas = leer_hoja(archivo, HOJA, columnas)

        plan = self.planear(filas, usuario)
        self.mostrar(plan)

        if not options["confirmar"]:
            self.stdout.write(
                self.style.WARNING(
                    "SIMULACIÓN: no se guardó ningún cambio. "
                    "Usa --confirmar para aplicar."
                )
            )
            return

        with transaction.atomic():
            MantenimientoEquipo.objects.bulk_create(plan["crear"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Importación completada: {len(plan['crear'])} "
                "mantenimientos creados."
            )
        )

    def planear(self, filas, usuario):
        """Calcula qué mantenimientos se crearían, sin guardar.

        Cuenta los que ya existen, los repetidos en el Sheet y los que no tienen
        equipo en la plataforma.
        """
        plan = {
            "crear": [],
            "existentes": 0,
            "repetidos": 0,
            "sin_equipo": {},
            "omitidos": [],
        }

        equipos = list(Equipo.objects.all())
        por_placa = {normalizar_placa(e.placa): e for e in equipos}
        # Respaldo para placas escritas distinto (RJ-093, PC-01 por PC--01):
        # solo cuando la clave sigue siendo de un único equipo.
        por_clave = {}
        for e in equipos:
            por_clave.setdefault(clave_placa(e.placa), []).append(e)
        # Solo como pista para la revisión manual: el número de la placa
        # de un radio suele ser su código físico, pero no siempre.
        por_codigo = {
            clave_placa(f"RJ-{r.codigo_fisico}"): r
            for r in Radio.objects.exclude(codigo_fisico="")
        }
        nuevos = set()
        existentes = {
            (
                m.equipo_id,
                timezone.localtime(m.fecha_intervencion, ZONA_COLOMBIA).date(),
                m.tipo,
            )
            for m in MantenimientoEquipo.objects.all()
        }

        for fila in filas:
            placa = normalizar_placa(fila[COL_PLACA])
            if not placa:
                plan["omitidos"].append(f"Fila {fila['_fila']}: sin placa.")
                continue
            etiqueta = f"Fila {fila['_fila']} ({placa})"

            equipo = por_placa.get(placa)
            if not equipo:
                candidatos = por_clave.get(clave_placa(placa), [])
                equipo = candidatos[0] if len(candidatos) == 1 else None
            if not equipo:
                n, pista = plan["sin_equipo"].get(
                    placa, (0, por_codigo.get(clave_placa(placa)))
                )
                plan["sin_equipo"][placa] = (n + 1, pista)
                continue

            dia = fecha_local(fila[COL_FECHA])
            if not dia:
                plan["omitidos"].append(f"{etiqueta}: fecha no reconocida.")
                continue

            tipo_original = texto_celda(fila[COL_TIPO])
            tipo = obtener_tipo(tipo_original)
            if not tipo:
                plan["omitidos"].append(
                    f"{etiqueta}: tipo no reconocido {tipo_original!r}."
                )
                continue

            clave = (equipo.pk, dia, tipo)
            if clave in existentes:
                plan["existentes"] += 1
                continue
            if clave in nuevos:
                plan["repetidos"] += 1
                continue
            nuevos.add(clave)

            actividad = texto_celda(fila[COL_ACTIVIDAD])
            causa = texto_celda(fila[COL_CAUSA])
            falla = texto_celda(fila[COL_FALLA])
            estado = texto_celda(fila[COL_ESTADO])
            if tipo == MantenimientoEquipo.Tipo.PREVENTIVO:
                motivo = causa or "Mantenimiento preventivo"
            else:
                motivo = causa or falla or SIN_DATO

            plan["crear"].append(MantenimientoEquipo(
                equipo=equipo,
                fecha_intervencion=timezone.make_aware(
                    datetime.combine(dia, time()), ZONA_COLOMBIA
                ),
                tipo=tipo,
                tecnico_responsable=(
                    texto_celda(fila[COL_ESPECIALISTA]) or SIN_DATO
                )[:150],
                motivo=motivo,
                diagnostico=causa,
                trabajo_realizado=actividad or falla or SIN_DATO,
                resultado=obtener_resultado(estado),
                estado_final=obtener_estado_final(estado),
                observaciones=(
                    f"Importado de la hoja {HOJA} del Google Sheet "
                    f"(fila {fila['_fila']} al importar).\n"
                    f"Código de búsqueda: {texto_celda(fila[COL_CODIGO])}\n"
                    f"Funcionario responsable: "
                    f"{texto_celda(fila[COL_RESPONSABLE]) or 'Sin dato'}\n"
                    f"Estado final original: {estado or 'Sin dato'}"
                ),
                registrado_por=usuario,
                origen_archivo=ORIGEN,
                origen_hoja=HOJA,
            ))

        return plan

    def mostrar(self, plan):
        """Imprime el resumen del plan."""
        self.stdout.write(f"Mantenimientos a crear: {len(plan['crear'])}")
        self.stdout.write(f"Ya registrados en la plataforma: {plan['existentes']}")
        self.stdout.write(f"Repetidos dentro del Sheet: {plan['repetidos']}")
        sin_equipo = sum(n for n, _ in plan["sin_equipo"].values())
        self.stdout.write(
            f"Filas con placas sin equipo en la plataforma: {sin_equipo} "
            f"({len(plan['sin_equipo'])} placas)"
        )
        for placa, (n, pista) in sorted(plan["sin_equipo"].items()):
            detalle = (
                f"; código físico de {pista.etiqueta} "
                f"(placa {pista.placa or 'vacía'}, serial {pista.serial})"
                if pista else ""
            )
            self.stdout.write(f"  {placa}: {n} filas{detalle}")
        if plan["omitidos"]:
            self.stdout.write("\nOmitidos:")
            for linea in plan["omitidos"]:
                self.stdout.write(self.style.WARNING(f"  {linea}"))
