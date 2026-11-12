"""Estado del mantenimiento preventivo de los equipos (semáforo).

La regla es la misma de las alertas: el siguiente mantenimiento vence seis
meses después de la última intervención (en hora de Colombia).
"""
from calendar import monthrange
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Max, Min, Q
from django.utils import timezone

from .models import MantenimientoProgramado


ZONA_COLOMBIA = ZoneInfo("America/Bogota")
DIAS_PROXIMO = 30

VENCIDO = "VENCIDO"
PROXIMO = "PROXIMO"
VIGENTE = "VIGENTE"
SIN_MANTENIMIENTO = "SIN_MANTENIMIENTO"

# Del más urgente al menos urgente: es el orden de las columnas del resumen y de la lista. "Sin mantenimiento" va justo después de
# "Vencido" porque tampoco cuenta como "al día".
ESTADOS = [
    (VENCIDO, "Vencido"),
    (SIN_MANTENIMIENTO, "Sin mantenimiento"),
    (PROXIMO, f"Vence en {DIAS_PROXIMO} días"),
    (VIGENTE, "Vigente"),
]


def sumar_seis_meses(fecha):
    mes_total = fecha.month - 1 + 6
    anio = fecha.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(fecha.day, monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def fecha_local(momento):
    return timezone.localtime(momento, ZONA_COLOMBIA).date()


def hoy_colombia():
    """Fecha de hoy en Colombia, la misma zona con la que se calculan los
    vencimientos (así no depende de la zona configurada en el servidor)."""
    return fecha_local(timezone.now())


def estado(ultima, hoy):
    """(estado, próximo vencimiento) a partir de la última intervención."""
    if ultima is None:
        return SIN_MANTENIMIENTO, None
    proximo = sumar_seis_meses(fecha_local(ultima))
    if proximo < hoy:
        return VENCIDO, proximo
    if proximo <= hoy + timedelta(days=DIAS_PROXIMO):
        return PROXIMO, proximo
    return VIGENTE, proximo


def _plural(cantidad, singular, plural):
    return f"{cantidad} {singular if cantidad == 1 else plural}"


def _tiempo_aproximado(dias):
    """'2 años y 4 meses' para un número de días (meses de 30 días)."""
    anios, meses = divmod(dias // 30, 12)
    partes = []
    if anios:
        partes.append(_plural(anios, "año", "años"))
    if meses:
        partes.append(_plural(meses, "mes", "meses"))
    return " y ".join(partes)


def describir_plazo(dias):
    """Texto corto para 'días para vencer' (negativo = atrasado)."""
    if dias is None:
        return ""
    if dias == 0:
        return "Vence hoy"
    if dias > 0:
        return f"Faltan {_plural(dias, 'día', 'días')}"
    atraso = _plural(-dias, "día", "días")
    if -dias >= 60:
        return f"{atraso} de atraso (≈ {_tiempo_aproximado(-dias)})"
    return f"{atraso} de atraso"


def equipos_con_estado(equipos, hoy=None):
    """Anota cada equipo y devuelve una lista. Atributos que agrega:

    - ultimo_mantenimiento: momento de la última intervención (o None).
    - ultimo_fecha: esa misma fecha en hora de Colombia, la que se muestra.
    - proximo_mantenimiento: fecha en que vence el siguiente (o None).
    - estado_mantenimiento: VENCIDO, PROXIMO, VIGENTE o SIN_MANTENIMIENTO.
    - dias_para_vencer / plazo_texto: días que faltan (negativo = atrasado)
      y su descripción.
    - proximo_programado: fecha de la visita ya programada (o None) y
      programado_atrasado si esa fecha ya pasó sin cumplirse.
    """
    hoy = hoy or hoy_colombia()
    resultado = []
    consulta = equipos.annotate(
        ultimo_mantenimiento=Max("mantenimientos__fecha_intervencion"),
        proximo_programado=Min(
            "mantenimientos_programados__fecha_programada",
            filter=Q(
                mantenimientos_programados__estado=(
                    MantenimientoProgramado.Estado.PROGRAMADO
                )
            ),
        ),
    )
    for equipo in consulta:
        equipo.estado_mantenimiento, equipo.proximo_mantenimiento = estado(
            equipo.ultimo_mantenimiento, hoy
        )
        equipo.ultimo_fecha = (
            fecha_local(equipo.ultimo_mantenimiento)
            if equipo.ultimo_mantenimiento else None
        )
        if equipo.proximo_mantenimiento:
            equipo.dias_para_vencer = (equipo.proximo_mantenimiento - hoy).days
        else:
            equipo.dias_para_vencer = None
        equipo.plazo_texto = describir_plazo(equipo.dias_para_vencer)
        equipo.programado_atrasado = bool(
            equipo.proximo_programado and equipo.proximo_programado < hoy
        )
        resultado.append(equipo)
    return resultado
