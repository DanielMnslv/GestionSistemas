"""Agenda de visitas de soporte (reemplaza a Calendly).

El solicitante elige un día hábil y una franja (8:00 a 12:00 o 2:00 a 5:00).
Cada franja tiene un número de cupos; los días festivos de Colombia y los
fines de semana no se ofrecen.
"""
import os
from datetime import date, datetime, timedelta

from django.utils import timezone

CUPOS_POR_FRANJA = int(os.getenv("SOPORTE_CUPOS_FRANJA", "3"))
DIAS_HABILES_AGENDA = int(os.getenv("SOPORTE_DIAS_AGENDA", "10"))
DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _pascua(anio):
    """Domingo de Pascua (algoritmo de Gauss/Meeus)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes, dia = divmod(h + l_ - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def _lunes_siguiente(dia):
    """Ley Emiliani: el festivo pasa al lunes siguiente si no cae en lunes."""
    return dia + timedelta(days=(7 - dia.weekday()) % 7)


def festivos(anio):
    """Festivos de Colombia del año."""
    pascua = _pascua(anio)
    fijos = [date(anio, 1, 1), date(anio, 5, 1), date(anio, 7, 20), date(anio, 8, 7),
             date(anio, 12, 8), date(anio, 12, 25),
             pascua - timedelta(days=3), pascua - timedelta(days=2)]
    trasladables = [date(anio, 1, 6), date(anio, 3, 19), date(anio, 6, 29), date(anio, 8, 15),
                    date(anio, 10, 12), date(anio, 11, 1), date(anio, 11, 11),
                    pascua + timedelta(days=39), pascua + timedelta(days=60),
                    pascua + timedelta(days=68)]
    return set(fijos) | {_lunes_siguiente(d) for d in trasladables}


def es_habil(dia):
    return dia.weekday() < 5 and dia not in festivos(dia.year)


def nombre_dia(dia):
    return f"{DIAS_SEMANA[dia.weekday()]} {dia.day} {MESES[dia.month - 1]}"


def franjas():
    from .models import Ticket
    return list(Ticket.Franja.choices)


def ocupacion(desde, hasta):
    """{(fecha, franja): cantidad de solicitudes activas agendadas}."""
    from .models import Ticket
    filas = (
        Ticket.objects.filter(fecha_programada__range=(desde, hasta))
        .exclude(estado__in=[Ticket.Estado.CANCELADO])
        .exclude(franja="")
        .values_list("fecha_programada", "franja")
    )
    conteo = {}
    for fecha, franja in filas:
        conteo[(fecha, franja)] = conteo.get((fecha, franja), 0) + 1
    return conteo


def dias_habiles(desde, cantidad):
    dias, dia = [], desde
    while len(dias) < cantidad:
        if es_habil(dia):
            dias.append(dia)
        dia += timedelta(days=1)
    return dias


def cupos_disponibles(ahora=None):
    """Lista de {fecha, franja, etiqueta, libres} con cupo, desde hoy.

    Hoy solo se ofrece la tarde y solo si aún no es mediodía.
    """
    ahora = timezone.localtime(ahora) if ahora else timezone.localtime()
    hoy = ahora.date()
    dias = dias_habiles(hoy, DIAS_HABILES_AGENDA + 1)
    ocupado = ocupacion(dias[0], dias[-1])
    resultado = []
    for dia in dias:
        for valor, texto in franjas():
            if dia == hoy and (valor == "MANANA" or ahora.hour >= 12):
                continue
            libres = CUPOS_POR_FRANJA - ocupado.get((dia, valor), 0)
            if libres > 0:
                resultado.append({
                    "fecha": dia, "franja": valor, "libres": libres,
                    "valor": f"{dia.isoformat()}|{valor}",
                    "etiqueta": f"{nombre_dia(dia)} · {texto}",
                })
    return resultado


def leer_valor(valor):
    """'2026-11-16|MANANA' -> (date, 'MANANA') o (None, '')."""
    try:
        fecha, franja = valor.split("|")
        return datetime.strptime(fecha, "%Y-%m-%d").date(), franja
    except (AttributeError, ValueError):
        return None, ""


def hay_cupo(fecha, franja):
    return ocupacion(fecha, fecha).get((fecha, franja), 0) < CUPOS_POR_FRANJA
