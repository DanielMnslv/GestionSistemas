"""Informes de seguridad informática: política de seguridad y antivirus."""
from .. import politica
from ..estado_mantenimiento import fecha_local, hoy_colombia
from ..models import DetalleComputador, Equipo, RenovacionAntivirus, VerificacionPolitica
from .ayudas import clave_placa, dias_entre, opciones_con_todos, ordenar_por_placa
from .base import Columna, Filtro, Informe

CATEGORIA = "Seguridad informática"
TIPOS_CON_POLITICA = (Equipo.Tipo.COMPUTADOR, Equipo.Tipo.TABLETA)
ETIQUETA_TIPO = dict(Equipo.Tipo.choices)
ETIQUETA_ESTADO = dict(politica.ESTADOS)
FILTRO_TIPO = Filtro("tipo", "Tipo de equipo", "select", opciones_con_todos((
    (Equipo.Tipo.COMPUTADOR, "Computador"), (Equipo.Tipo.TABLETA, "Tableta"))))


def _ultimas_verificaciones():
    """Última verificación de política de cada equipo: {equipo_id: verificación}."""
    ultimas = {}
    for v in VerificacionPolitica.objects.order_by("-fecha", "-id"):
        ultimas.setdefault(v.equipo_id, v)
    return ultimas


def _contar_respuestas(respuestas):
    """Cuenta las respuestas (cumple, no cumple, no aplica) de una verificación."""
    valores = list((respuestas or {}).values())
    return (valores.count(politica.CUMPLE), valores.count(politica.NO_CUMPLE), valores.count(politica.NO_APLICA))


def _equipos(valores):
    """Computadores y tabletas activos, filtrados por tipo si se eligió."""
    consulta = Equipo.objects.filter(activo=True, tipo__in=TIPOS_CON_POLITICA)
    if valores["tipo"]:
        consulta = consulta.filter(tipo=valores["tipo"])
    return consulta


class EstadoPolitica(Informe):
    """Informe «Política de seguridad: estado de cada equipo».

    Cada computador y tableta con su última verificación anual y si vence, cumple o tiene incumplimientos.
    """
    clave = "politica_estado"
    titulo = "Política de seguridad: estado de cada equipo"
    categoria = CATEGORIA
    descripcion = "Cada computador y tableta con su última verificación anual y si vence, cumple o tiene incumplimientos."
    columnas = (
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1), Columna("equipo", "Marca y modelo", 1.8),
        Columna("responsable", "Responsable", 2), Columna("ubicacion", "Ubicación", 2),
        Columna("ultima", "Última verificación", 1.2, "der"), Columna("vence", "Vence", 1, "der"),
        Columna("estado", "Estado", 1.4, "centro", tono=True), Columna("incumple", "Puntos que no cumple", 0.9, "der"),
    )
    columnas_pdf = ("placa", "tipo", "equipo", "responsable", "ultima", "vence", "estado", "incumple")
    filtros = (FILTRO_TIPO, Filtro("estado", "Estado", "select", opciones_con_todos(politica.ESTADOS)))

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Política de seguridad: estado de cada equipo» según los filtros elegidos (``valores``)."""
        hoy = hoy_colombia()
        ultimas = _ultimas_verificaciones()
        filas = []
        for e in _equipos(valores):
            v = ultimas.get(e.pk)
            ultima = fecha_local(v.fecha) if v else None
            incumple = _contar_respuestas(v.respuestas)[1] if v else 0
            estado, vence = politica.estado_verificacion(ultima, incumple, hoy)
            if valores["estado"] and estado != valores["estado"]:
                continue
            filas.append({
                "placa": e.placa, "tipo": ETIQUETA_TIPO.get(e.tipo, e.tipo),
                "equipo": f"{e.marca} {e.modelo}".strip(), "responsable": e.responsable_nombre,
                "ubicacion": e.ubicacion, "ultima": ultima, "vence": vence,
                "estado": ETIQUETA_ESTADO[estado], "incumple": incumple, "_orden": estado,
            })
        orden = {codigo: i for i, (codigo, _) in enumerate(politica.ESTADOS)}
        filas.sort(key=lambda f: (orden[f["_orden"]], clave_placa(f["placa"])))
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Equipos."""
        etiquetas = [e for _, e in politica.ESTADOS]
        conteo = {e: 0 for e in etiquetas}
        for f in filas:
            conteo[f["estado"]] += 1
        return [("Equipos", len(filas))] + [(e, conteo[e]) for e in etiquetas if conteo[e]]


class IncumplimientosPolitica(Informe):
    """Informe «Política de seguridad: puntos incumplidos por equipo».

    Una línea por cada punto de la política que el equipo no cumple en su última verificación.
    """
    clave = "politica_incumplimientos"
    titulo = "Política de seguridad: puntos incumplidos por equipo"
    categoria = CATEGORIA
    descripcion = "Una línea por cada punto de la política que el equipo no cumple en su última verificación."
    columnas = (
        Columna("placa", "Placa", 1), Columna("responsable", "Responsable", 2),
        Columna("fecha", "Verificado", 1.1, "der"), Columna("especialista", "Especialista", 1.6),
        Columna("punto", "Punto que no cumple", 5),
    )
    filtros = (FILTRO_TIPO,)

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Política de seguridad: puntos incumplidos por equipo» según los filtros elegidos (``valores``)."""
        ultimas = _ultimas_verificaciones()
        filas = []
        for e in _equipos(valores):
            v = ultimas.get(e.pk)
            if not v:
                continue
            for texto in v.incumplimientos:
                filas.append({"placa": e.placa, "responsable": v.responsable or e.responsable_nombre,
                              "fecha": v.fecha, "especialista": v.especialista, "punto": texto})
        return ordenar_por_placa(filas)

    def resumen(self, filas):
        """Totales del encabezado: Puntos incumplidos, Equipos afectados."""
        return [("Puntos incumplidos", len(filas)), ("Equipos afectados", len({f["placa"] for f in filas}))]


class PuntosMasIncumplidos(Informe):
    """Informe «Política de seguridad: cumplimiento por punto».

    Para cada uno de los 15 puntos de la política, cuántos equipos cumplen y cuántos no (última verificación).
    """
    clave = "politica_puntos"
    titulo = "Política de seguridad: cumplimiento por punto"
    categoria = CATEGORIA
    descripcion = "Para cada uno de los 15 puntos de la política, cuántos equipos cumplen y cuántos no (última verificación)."
    columnas = (
        Columna("punto", "Punto de la política", 5), Columna("cumple", "Cumple", 0.8, "der"),
        Columna("no_cumple", "No cumple", 0.8, "der"), Columna("no_aplica", "No aplica", 0.8, "der"),
        Columna("porcentaje", "% de cumplimiento", 1, "der"),
    )
    orientacion = "vertical"
    filtros = (FILTRO_TIPO,)

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Política de seguridad: cumplimiento por punto» según los filtros elegidos (``valores``)."""
        ultimas = _ultimas_verificaciones()
        conteos = {c: {"cumple": 0, "no_cumple": 0, "no_aplica": 0} for c, _ in politica.PUNTOS}
        for e in _equipos(valores):
            v = ultimas.get(e.pk)
            if not v:
                continue
            for clave, valor in (v.respuestas or {}).items():
                if clave not in conteos:
                    continue
                if valor == politica.CUMPLE:
                    conteos[clave]["cumple"] += 1
                elif valor == politica.NO_CUMPLE:
                    conteos[clave]["no_cumple"] += 1
                elif valor == politica.NO_APLICA:
                    conteos[clave]["no_aplica"] += 1
        filas = []
        for clave, texto in politica.PUNTOS:
            c = conteos[clave]
            evaluados = c["cumple"] + c["no_cumple"]
            filas.append({"punto": texto, **c,
                          "porcentaje": f"{round(100 * c['cumple'] / evaluados)} %" if evaluados else "—"})
        filas.sort(key=lambda f: -f["no_cumple"])
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Puntos evaluados, Con algún incumplimiento."""
        return [("Puntos evaluados", len(filas)),
                ("Con algún incumplimiento", sum(1 for f in filas if f["no_cumple"]))]


class HistorialPolitica(Informe):
    """Informe «Verificaciones de la política realizadas».

    Historial de verificaciones por rango de fechas, con la cantidad de puntos que cumplen y no cumplen.
    """
    clave = "politica_verificaciones"
    titulo = "Verificaciones de la política realizadas"
    categoria = CATEGORIA
    descripcion = "Historial de verificaciones por rango de fechas, con la cantidad de puntos que cumplen y no cumplen."
    columnas = (
        Columna("fecha", "Fecha", 1.2, "der"), Columna("placa", "Placa", 1),
        Columna("responsable", "Responsable", 1.8), Columna("especialista", "Especialista", 1.6),
        Columna("cumple", "Cumple", 0.7, "der"), Columna("no_cumple", "No cumple", 0.7, "der"),
        Columna("no_aplica", "No aplica", 0.7, "der"), Columna("observaciones", "Observaciones", 3),
        Columna("actualizacion", "Actualizaciones realizadas", 2.5),
    )
    columnas_pdf = ("fecha", "placa", "responsable", "especialista", "cumple", "no_cumple", "observaciones")
    filtros = (Filtro("desde", "Desde", "date"), Filtro("hasta", "Hasta", "date"), FILTRO_TIPO,
               Filtro("solo_incumple", "Solo con incumplimientos", "checkbox"))

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Verificaciones de la política realizadas» según los filtros elegidos (``valores``)."""
        consulta = VerificacionPolitica.objects.select_related("equipo")
        if valores["desde"]:
            consulta = consulta.filter(fecha__date__gte=valores["desde"])
        if valores["hasta"]:
            consulta = consulta.filter(fecha__date__lte=valores["hasta"])
        if valores["tipo"]:
            consulta = consulta.filter(equipo__tipo=valores["tipo"])
        filas = []
        for v in consulta:
            cumple, no_cumple, no_aplica = _contar_respuestas(v.respuestas)
            if valores["solo_incumple"] and not no_cumple:
                continue
            filas.append({
                "fecha": v.fecha, "placa": v.equipo.placa, "responsable": v.responsable,
                "especialista": v.especialista, "cumple": cumple, "no_cumple": no_cumple,
                "no_aplica": no_aplica, "observaciones": v.observaciones, "actualizacion": v.actualizacion,
            })
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Verificaciones, Equipos verificados, Con incumplimientos."""
        return [("Verificaciones", len(filas)), ("Equipos verificados", len({f["placa"] for f in filas})),
                ("Con incumplimientos", sum(1 for f in filas if f["no_cumple"]))]


SIN_FECHA = "Sin fecha registrada"
ESTADOS_ANTIVIRUS = (
    ("vencido", "Vencido"), ("proximo", f"Vence en {politica.DIAS_PROXIMO} días"),
    ("vigente", "Vigente"), ("sin_fecha", SIN_FECHA),
)


def _estado_antivirus(vencimiento, hoy):
    """Estado del antivirus según su vencimiento: sin fecha, vencido, por vencer o vigente."""
    if vencimiento is None:
        return "sin_fecha"
    dias = dias_entre(vencimiento, hoy)
    if dias < 0:
        return "vencido"
    if dias <= politica.DIAS_PROXIMO:
        return "proximo"
    return "vigente"


class AntivirusVencimientos(Informe):
    """Informe «Licencias de antivirus: vencimientos».

    Qué antivirus tiene cada computador y cuándo vence. No incluye las claves de licencia.
    """
    clave = "antivirus_vencimientos"
    titulo = "Licencias de antivirus: vencimientos"
    categoria = CATEGORIA
    descripcion = "Qué antivirus tiene cada computador y cuándo vence. No incluye las claves de licencia."
    columnas = (
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1), Columna("equipo", "Marca y modelo", 1.8),
        Columna("responsable", "Responsable", 2), Columna("antivirus", "Antivirus", 1.6),
        Columna("vencimiento", "Vencimiento", 1.1, "der"), Columna("dias", "Días", 0.7, "der"),
        Columna("estado", "Estado", 1.4, "centro", tono=True),
    )
    filtros = (FILTRO_TIPO, Filtro("estado", "Estado", "select", opciones_con_todos(ESTADOS_ANTIVIRUS)))

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Licencias de antivirus: vencimientos» según los filtros elegidos (``valores``)."""
        hoy = hoy_colombia()
        etiquetas = dict(ESTADOS_ANTIVIRUS)
        consulta = DetalleComputador.objects.filter(equipo__activo=True).select_related("equipo")
        if valores["tipo"]:
            consulta = consulta.filter(equipo__tipo=valores["tipo"])
        filas = []
        for d in consulta:
            estado = _estado_antivirus(d.vencimiento_antivirus, hoy)
            if valores["estado"] and estado != valores["estado"]:
                continue
            e = d.equipo
            filas.append({
                "placa": e.placa, "tipo": ETIQUETA_TIPO.get(e.tipo, e.tipo),
                "equipo": f"{e.marca} {e.modelo}".strip(), "responsable": e.responsable_nombre,
                "antivirus": d.antivirus or "Sin antivirus registrado",
                "vencimiento": d.vencimiento_antivirus, "dias": dias_entre(d.vencimiento_antivirus, hoy),
                "estado": etiquetas[estado], "_estado": estado,
            })
        orden = {codigo: i for i, (codigo, _) in enumerate(ESTADOS_ANTIVIRUS)}
        filas.sort(key=lambda f: (orden[f["_estado"]], f["dias"] if f["dias"] is not None else 0,
                                  clave_placa(f["placa"])))
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Computadores."""
        etiquetas = [e for _, e in ESTADOS_ANTIVIRUS]
        conteo = {e: 0 for e in etiquetas}
        for f in filas:
            conteo[f["estado"]] += 1
        return [("Computadores", len(filas))] + [(e, conteo[e]) for e in etiquetas if conteo[e]]


class AntivirusRenovaciones(Informe):
    """Informe «Renovaciones de antivirus registradas».

    Historial de renovaciones de licencia por rango de fechas. No incluye las claves.
    """
    clave = "antivirus_renovaciones"
    titulo = "Renovaciones de antivirus registradas"
    categoria = CATEGORIA
    descripcion = "Historial de renovaciones de licencia por rango de fechas. No incluye las claves."
    columnas = (
        Columna("fecha", "Fecha", 1.2, "der"), Columna("placa", "Placa", 1),
        Columna("responsable", "Responsable del equipo", 2), Columna("antivirus", "Antivirus", 2),
        Columna("vencimiento", "Nuevo vencimiento", 1.2, "der"), Columna("registro", "Registró", 1.5),
        Columna("origen", "Origen", 1),
    )
    filtros = (Filtro("desde", "Desde", "date"), Filtro("hasta", "Hasta", "date"))

    def obtener_filas(self, valores, usuario=None):
        """Filas de «Renovaciones de antivirus registradas» según los filtros elegidos (``valores``)."""
        consulta = RenovacionAntivirus.objects.select_related("equipo", "registrado_por")
        if valores["desde"]:
            consulta = consulta.filter(fecha__date__gte=valores["desde"])
        if valores["hasta"]:
            consulta = consulta.filter(fecha__date__lte=valores["hasta"])
        filas = []
        for r in consulta:
            u = r.registrado_por
            filas.append({
                "fecha": r.fecha, "placa": r.equipo.placa, "responsable": r.equipo.responsable_nombre,
                "antivirus": r.antivirus, "vencimiento": r.vencimiento,
                "registro": (u.get_full_name() or u.get_username()) if u else "",
                "origen": "Importada" if r.importada else "Manual",
            })
        return filas

    def resumen(self, filas):
        """Totales del encabezado: Renovaciones."""
        return [("Renovaciones", len(filas))]


INFORMES = [EstadoPolitica(), IncumplimientosPolitica(), PuntosMasIncumplidos(),
            HistorialPolitica(), AntivirusVencimientos(), AntivirusRenovaciones()]
