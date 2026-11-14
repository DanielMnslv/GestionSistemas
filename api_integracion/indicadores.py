"""Resumen de indicadores de JANO Inventario para Gestión TIC.

Cada métrica entrega {nombre, descripcion, valor, meta, pct, unidad,
pendientes}: `valor` es lo logrado y `meta` lo esperado en el periodo, igual
que los indicadores automáticos de Gestión TIC. Los estados se calculan a la
fecha de corte (el último día del periodo, o hoy si el periodo sigue en
curso), con las mismas reglas que usa JANO en sus pantallas.
"""
from datetime import date, datetime, time, timedelta

from django.db.models import Max, Q
from django.utils import timezone

from inventario import politica
from inventario.estado_mantenimiento import (
    PROXIMO,
    VIGENTE,
    ZONA_COLOMBIA,
    estado as estado_mantenimiento,
    hoy_colombia,
)
from inventario.models import (
    DetalleComputador,
    Equipo,
    MantenimientoEquipo,
    MantenimientoProgramado,
    RetiroFuncionario,
    VerificacionPolitica,
)

MAX_PENDIENTES = 50

METRICAS = {
    "mantenimiento_al_dia": "Equipos con mantenimiento al día",
    "mantenimiento_computadores": "Computadores con mantenimiento al día",
    "mantenimiento_radios": "Radios con mantenimiento al día",
    "ejecucion_programacion": "Mantenimientos programados ejecutados",
    "mantenimientos_realizados": "Mantenimientos realizados",
    "politica_al_dia": "Computadores con política de seguridad al día",
    "antivirus_vigente": "Computadores con antivirus vigente",
    "paz_y_salvo": "Retiros con paz y salvo emitido",
}


def _fin_del_dia(fecha):
    """Inicio del día siguiente (hora de Colombia), como límite superior del día."""
    return timezone.make_aware(datetime.combine(fecha + timedelta(days=1), time.min), ZONA_COLOMBIA)


def _inicio_del_dia(fecha):
    """Inicio del día (00:00, hora de Colombia)."""
    return timezone.make_aware(datetime.combine(fecha, time.min), ZONA_COLOMBIA)


def _metrica(clave, descripcion, valor, meta, unidad="equipos", pendientes=None):
    """Arma una métrica con su valor, meta, porcentaje de cumplimiento y pendientes."""
    pct = round(valor * 100 / meta, 1) if meta else None
    return {
        "clave": clave,
        "nombre": METRICAS[clave],
        "descripcion": descripcion,
        "valor": valor,
        "meta": meta,
        "pct": pct,
        "unidad": unidad,
        "pendientes": (pendientes or [])[:MAX_PENDIENTES],
        "total_pendientes": len(pendientes or []),
    }


def _mantenimiento(clave, equipos, corte, descripcion):
    """Métrica de equipos con mantenimiento vigente a la fecha de corte."""
    limite = _fin_del_dia(corte)
    consulta = equipos.annotate(
        ultima=Max(
            "mantenimientos__fecha_intervencion",
            filter=Q(mantenimientos__fecha_intervencion__lt=limite),
        )
    ).order_by("tipo", "placa")
    al_dia, pendientes = 0, []
    for e in consulta:
        estado, proximo = estado_mantenimiento(e.ultima, corte)
        if estado in (VIGENTE, PROXIMO):
            al_dia += 1
        else:
            pendientes.append({
                "placa": e.placa, "tipo": e.get_tipo_display(),
                "estado": "Sin mantenimiento" if e.ultima is None else "Vencido",
                "vencio": proximo.isoformat() if proximo else None,
            })
    return _metrica(clave, descripcion, al_dia, len(consulta), pendientes=pendientes)


def resumen_indicadores(desde, hasta, hoy=None):
    """Indicadores de JANO para Gestión TIC en el período ``desde``–``hasta``.

    La fecha de corte es el final del período o hoy, lo que ocurra primero.
    Incluye cada métrica de ``METRICAS`` (mantenimiento al día, programación
    ejecutada, política, antivirus y paz y salvo), cada una con su meta.
    """
    hoy = hoy or hoy_colombia()
    corte = min(hasta, hoy)
    activos = Equipo.objects.filter(activo=True)
    computadores = activos.filter(tipo=Equipo.Tipo.COMPUTADOR)
    regla = "Al día = último mantenimiento hace menos de 6 meses a la fecha de corte."

    metricas = [
        _mantenimiento("mantenimiento_al_dia", activos, corte, regla),
        _mantenimiento("mantenimiento_computadores", computadores, corte, regla),
        _mantenimiento("mantenimiento_radios", activos.filter(tipo=Equipo.Tipo.RADIO), corte, regla),
    ]

    # Programación: visitas con fecha dentro del periodo (sin las canceladas).
    programados = MantenimientoProgramado.objects.filter(
        fecha_programada__gte=desde, fecha_programada__lte=hasta,
    ).exclude(estado=MantenimientoProgramado.Estado.CANCELADO).select_related("equipo")
    pendientes = [
        {"placa": p.equipo.placa, "tipo": p.equipo.get_tipo_display(),
         "estado": "Atrasado" if p.fecha_programada < hoy else "Programado",
         "fecha": p.fecha_programada.isoformat()}
        for p in programados if p.estado != MantenimientoProgramado.Estado.COMPLETADO
    ]
    metricas.append(_metrica(
        "ejecucion_programacion",
        "Visitas programadas en el periodo que ya quedaron completadas.",
        sum(1 for p in programados if p.estado == MantenimientoProgramado.Estado.COMPLETADO),
        len(programados), unidad="visitas", pendientes=pendientes,
    ))

    # Intervenciones registradas en el periodo (informativo: sin meta).
    realizados = MantenimientoEquipo.objects.filter(
        fecha_intervencion__gte=_inicio_del_dia(desde),
        fecha_intervencion__lt=_fin_del_dia(hasta),
    )
    preventivos = realizados.filter(tipo=MantenimientoEquipo.Tipo.PREVENTIVO).count()
    total = realizados.count()
    m = _metrica(
        "mantenimientos_realizados",
        f"Intervenciones registradas en el periodo ({preventivos} preventivas).",
        total, None, unidad="intervenciones",
    )
    m["preventivos"] = preventivos
    metricas.append(m)

    # Política de seguridad: verificación anual sin incumplimientos.
    limite = _fin_del_dia(corte)
    ultimas = {}
    for v in VerificacionPolitica.objects.filter(
        equipo__in=computadores, fecha__lt=limite
    ).order_by("equipo_id", "fecha").only("equipo_id", "fecha", "respuestas"):
        ultimas[v.equipo_id] = v
    al_dia, pendientes = 0, []
    for e in computadores.order_by("placa"):
        v = ultimas.get(e.pk)
        fecha_v = timezone.localtime(v.fecha, ZONA_COLOMBIA).date() if v else None
        estado, vence = politica.estado_verificacion(
            fecha_v, len(politica.incumplimientos(v.respuestas)) if v else 0, corte
        )
        if estado in (politica.AL_DIA, politica.PROXIMA):
            al_dia += 1
        else:
            pendientes.append({
                "placa": e.placa, "tipo": e.get_tipo_display(),
                "estado": dict(politica.ESTADOS)[estado],
                "vencio": vence.isoformat() if vence else None,
            })
    metricas.append(_metrica(
        "politica_al_dia",
        "Verificación anual hecha, vigente y sin incumplimientos a la fecha de corte.",
        al_dia, computadores.count(), pendientes=pendientes,
    ))

    # Antivirus: licencias con fecha de vencimiento registrada.
    detalles = DetalleComputador.objects.filter(
        equipo__in=computadores, vencimiento_antivirus__isnull=False
    ).select_related("equipo").order_by("equipo__placa")
    vigentes = [d for d in detalles if d.vencimiento_antivirus >= corte]
    metricas.append(_metrica(
        "antivirus_vigente",
        "Computadores con licencia de antivirus vigente a la fecha de corte "
        f"({computadores.count() - len(detalles)} sin fecha registrada no se cuentan).",
        len(vigentes), len(detalles),
        pendientes=[
            {"placa": d.equipo.placa, "tipo": "Computador", "estado": "Vencido",
             "vencio": d.vencimiento_antivirus.isoformat()}
            for d in detalles if d.vencimiento_antivirus < corte
        ],
    ))

    # Paz y salvo: retiros del periodo que ya quedaron cerrados.
    retiros = RetiroFuncionario.objects.filter(
        fecha_retiro__gte=desde, fecha_retiro__lte=hasta,
    ).exclude(estado=RetiroFuncionario.Estado.CANCELADO).select_related("funcionario")
    metricas.append(_metrica(
        "paz_y_salvo",
        "Retiros de personal del periodo con todos los equipos validados y paz y salvo emitido.",
        sum(1 for r in retiros if r.estado == RetiroFuncionario.Estado.PAZ_Y_SALVO),
        len(retiros), unidad="retiros",
        pendientes=[
            {"placa": r.funcionario.nombre_completo, "tipo": r.get_motivo_display(),
             "estado": "En proceso", "fecha": r.fecha_retiro.isoformat()}
            for r in retiros if r.estado == RetiroFuncionario.Estado.EN_PROCESO
        ],
    ))

    return {
        "fuente": "JANO Inventario",
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "fecha_corte": corte.isoformat(),
        "generado_en": timezone.now().isoformat(),
        "metricas": {m["clave"]: m for m in metricas},
    }


def periodo_desde_parametros(params, hoy=None):
    """(desde, hasta) de ?desde=AAAA-MM-DD&hasta=AAAA-MM-DD; por defecto el trimestre actual."""
    hoy = hoy or hoy_colombia()
    if params.get("desde") or params.get("hasta"):
        desde = date.fromisoformat(params["desde"])
        hasta = date.fromisoformat(params["hasta"])
    else:
        mes = (hoy.month - 1) // 3 * 3 + 1
        desde = date(hoy.year, mes, 1)
        hasta = (date(hoy.year + (mes + 3 > 12), (mes + 2) % 12 + 1, 1) - timedelta(days=1))
    if hasta < desde or (hasta - desde).days > 400:
        raise ValueError("Periodo no válido (máximo un año).")
    return desde, hasta
