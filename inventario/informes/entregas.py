"""Informes de entregas de radios y de equipos."""
from ..estado_mantenimiento import fecha_local, hoy_colombia
from ..models import AsignacionEquipo, AsignacionRadio, Equipo, TransferenciaComponentesRadio, Vigilante
from .ayudas import contiene, opciones_con_todos, texto_componente
from .base import Columna, Filtro, Informe

CATEGORIA = "Entregas"
ETIQUETA_TIPO = dict(Equipo.Tipo.choices)


def _nombres_vigilantes():
    return dict(Vigilante.objects.values_list("cedula", "nombre_completo"))


def _usuario(u):
    return "" if u is None else (u.get_full_name() or u.get_username())


def _dias_desde(momento, hoy):
    return (hoy - fecha_local(momento)).days


def _firma(a):
    return "Firmada" if (a.firma or a.enlace_firma) else "Sin firma"


def _recibe(a):
    return a.nombre_recibe or (a.funcionario.nombre_completo if a.funcionario else "")


def _cedula(a):
    return a.cedula_recibe or (a.funcionario.cedula if a.funcionario else "")


class RadiosEntregados(Informe):
    clave = "radios_entregados"
    titulo = "Radios entregados actualmente"
    categoria = CATEGORIA
    descripcion = "Qué vigilante tiene cada radio hoy, en qué cliente y puesto y desde cuándo."
    columnas = (
        Columna("radio", "Radio (RJ)", 1), Columna("serial", "Serial", 1.3), Columna("vigilante", "Vigilante", 2),
        Columna("cedula", "Cédula", 1.1), Columna("cliente", "Cliente", 2), Columna("puesto", "Puesto", 2),
        Columna("coordinador", "Coordinador de zona", 1.6), Columna("fecha", "Entregado", 1.3, "der"),
        Columna("dias", "Días", 0.7, "der"), Columna("firma", "Firma", 0.9, "centro", tono=True),
    )
    columnas_pdf = ("radio", "vigilante", "cedula", "cliente", "puesto", "coordinador", "fecha", "dias")
    filtros = (Filtro("cliente", "Cliente", ayuda="Parte del nombre del cliente."),
               Filtro("q", "Buscar", ayuda="Radio, vigilante, cédula, puesto o coordinador."))

    def obtener_filas(self, valores, usuario=None):
        hoy = hoy_colombia()
        nombres = _nombres_vigilantes()
        consulta = AsignacionRadio.objects.filter(estado=AsignacionRadio.Estado.ASIGNADO).select_related("radio")
        if valores["cliente"]:
            consulta = consulta.filter(cliente_asignado__icontains=valores["cliente"])
        filas = []
        for a in consulta:
            fila = {
                "radio": a.radio.etiqueta, "serial": a.radio.serial,
                "vigilante": nombres.get(a.cedula_funcionario, "No registrado"),
                "cedula": a.cedula_funcionario, "cliente": a.cliente_asignado,
                "puesto": a.puesto_asignado, "coordinador": a.coordinador_zona,
                "fecha": a.fecha_entrega, "dias": _dias_desde(a.fecha_entrega, hoy), "firma": _firma(a),
            }
            if valores["q"] and not any(contiene(fila[k], valores["q"])
                                        for k in ("radio", "vigilante", "cedula", "puesto", "coordinador")):
                continue
            filas.append(fila)
        filas.sort(key=lambda f: (f["cliente"].lower(), f["puesto"].lower(), f["vigilante"].lower()))
        return filas

    def resumen(self, filas):
        return [("Radios entregados", len(filas)),
                ("Vigilantes con radio", len({f["cedula"] for f in filas})),
                ("Clientes", len({f["cliente"] for f in filas})),
                ("Sin firma", sum(1 for f in filas if f["firma"] == "Sin firma"))]


class RadiosHistorialEntregas(Informe):
    clave = "radios_historial_entregas"
    titulo = "Historial de entregas y devoluciones de radios"
    categoria = CATEGORIA
    descripcion = "Todas las entregas de radios por rango de fechas, con su devolución."
    columnas = (
        Columna("fecha", "Entrega", 1.3, "der"), Columna("radio", "Radio (RJ)", 1),
        Columna("vigilante", "Vigilante", 2), Columna("cedula", "Cédula", 1.1),
        Columna("cliente", "Cliente", 2), Columna("puesto", "Puesto", 2),
        Columna("entregado_por", "Entregó", 1.3), Columna("estado", "Estado", 1, "centro", tono=True),
        Columna("devolucion", "Devolución", 1.3, "der"), Columna("recibido_por", "Recibió", 1.3),
    )
    columnas_pdf = ("fecha", "radio", "vigilante", "cliente", "puesto", "estado", "devolucion")
    filtros = (
        Filtro("desde", "Entregado desde", "date"), Filtro("hasta", "Entregado hasta", "date"),
        Filtro("estado", "Estado", "select", opciones_con_todos(AsignacionRadio.Estado.choices)),
        Filtro("q", "Buscar", ayuda="Radio, vigilante, cédula, cliente o puesto."),
    )

    def obtener_filas(self, valores, usuario=None):
        nombres = _nombres_vigilantes()
        consulta = AsignacionRadio.objects.select_related("radio", "entregado_por", "recibido_por")
        if valores["desde"]:
            consulta = consulta.filter(fecha_entrega__date__gte=valores["desde"])
        if valores["hasta"]:
            consulta = consulta.filter(fecha_entrega__date__lte=valores["hasta"])
        if valores["estado"]:
            consulta = consulta.filter(estado=valores["estado"])
        filas = []
        for a in consulta:
            fila = {
                "fecha": a.fecha_entrega, "radio": a.radio.etiqueta,
                "vigilante": nombres.get(a.cedula_funcionario, "No registrado"),
                "cedula": a.cedula_funcionario, "cliente": a.cliente_asignado, "puesto": a.puesto_asignado,
                "entregado_por": _usuario(a.entregado_por), "estado": a.get_estado_display(),
                "devolucion": a.fecha_devolucion, "recibido_por": _usuario(a.recibido_por),
            }
            if valores["q"] and not any(contiene(fila[k], valores["q"])
                                        for k in ("radio", "vigilante", "cedula", "cliente", "puesto")):
                continue
            filas.append(fila)
        return filas

    def resumen(self, filas):
        return [("Entregas", len(filas)),
                ("Vigentes", sum(1 for f in filas if f["estado"] == "Asignado")),
                ("Devueltas", sum(1 for f in filas if f["estado"] == "Devuelto"))]


class EntregasSinFirma(Informe):
    clave = "entregas_sin_firma"
    titulo = "Entregas vigentes sin firma o sin cláusula aceptada"
    categoria = CATEGORIA
    descripcion = "Radios y equipos entregados cuya acta no tiene firma o cuya cláusula no fue aceptada."
    columnas = (
        Columna("clase", "Entrega", 0.8), Columna("equipo", "Placa", 1), Columna("recibe", "Recibe", 2),
        Columna("cedula", "Cédula", 1.1), Columna("donde", "Cliente / área", 2.4),
        Columna("fecha", "Entregado", 1.3, "der"), Columna("dias", "Días", 0.7, "der"),
        Columna("falta", "Falta", 1.8),
    )

    def obtener_filas(self, valores, usuario=None):
        hoy = hoy_colombia()
        nombres = _nombres_vigilantes()
        filas = []

        def faltas(a):
            lista = []
            if not (a.firma or a.enlace_firma):
                lista.append("Firma")
            if not a.clausula_aceptada:
                lista.append("Cláusula")
            return lista

        for a in AsignacionRadio.objects.filter(estado=AsignacionRadio.Estado.ASIGNADO).select_related("radio"):
            if faltas(a):
                filas.append({
                    "clase": "Radio", "equipo": a.radio.etiqueta,
                    "recibe": nombres.get(a.cedula_funcionario, "No registrado"),
                    "cedula": a.cedula_funcionario,
                    "donde": f"{a.cliente_asignado} - {a.puesto_asignado}".strip(" -"),
                    "fecha": a.fecha_entrega, "dias": _dias_desde(a.fecha_entrega, hoy),
                    "falta": " y ".join(faltas(a)),
                })
        for a in AsignacionEquipo.objects.filter(estado=AsignacionEquipo.Estado.ASIGNADO).select_related(
                "equipo", "funcionario"):
            if faltas(a):
                filas.append({
                    "clase": ETIQUETA_TIPO.get(a.equipo.tipo, "Equipo"), "equipo": a.equipo.placa,
                    "recibe": _recibe(a), "cedula": _cedula(a), "donde": a.area,
                    "fecha": a.fecha_entrega, "dias": _dias_desde(a.fecha_entrega, hoy),
                    "falta": " y ".join(faltas(a)),
                })
        filas.sort(key=lambda f: -f["dias"])
        return filas

    def resumen(self, filas):
        return [("Entregas por regularizar", len(filas)),
                ("Radios", sum(1 for f in filas if f["clase"] == "Radio")),
                ("Otros equipos", sum(1 for f in filas if f["clase"] != "Radio"))]


class TransferenciasComponentes(Informe):
    clave = "radios_transferencias"
    titulo = "Transferencias de accesorios entre radios"
    categoria = CATEGORIA
    descripcion = "Trazabilidad de los accesorios (antenas, baterías, cargadores...) que se pasaron de un radio a otro."
    columnas = (
        Columna("fecha", "Fecha", 1.3, "der"), Columna("origen", "Radio de origen", 1.5),
        Columna("destino", "Radio de destino", 1.5), Columna("componentes", "Accesorios", 3.5),
        Columna("registro", "Registró", 1.5),
    )
    filtros = (Filtro("desde", "Desde", "date"), Filtro("hasta", "Hasta", "date"))

    def obtener_filas(self, valores, usuario=None):
        consulta = TransferenciaComponentesRadio.objects.select_related("registrado_por")
        if valores["desde"]:
            consulta = consulta.filter(fecha__date__gte=valores["desde"])
        if valores["hasta"]:
            consulta = consulta.filter(fecha__date__lte=valores["hasta"])
        return [{
            "fecha": t.fecha, "origen": t.etiqueta_origen, "destino": t.etiqueta_destino,
            "componentes": ", ".join(texto_componente(c) for c in (t.componentes or [])),
            "registro": _usuario(t.registrado_por),
        } for t in consulta]

    def resumen(self, filas):
        return [("Transferencias", len(filas))]


class EquiposEntregados(Informe):
    clave = "equipos_entregados"
    titulo = "Equipos entregados actualmente"
    categoria = CATEGORIA
    descripcion = "Computadores, tabletas, impresoras y otros equipos que hoy están a cargo de un funcionario."
    columnas = (
        Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1), Columna("equipo", "Marca y modelo", 1.8),
        Columna("serial", "Serial", 1.4), Columna("recibe", "Recibe", 2), Columna("cedula", "Cédula", 1.1),
        Columna("area", "Área", 1.8), Columna("accesorios", "Accesorios", 2),
        Columna("fecha", "Entregado", 1.3, "der"), Columna("dias", "Días", 0.7, "der"),
    )
    columnas_pdf = ("placa", "tipo", "equipo", "recibe", "cedula", "area", "accesorios", "fecha")
    filtros = (Filtro("tipo", "Tipo de equipo", "select", opciones_con_todos(Equipo.Tipo.choices)),
               Filtro("q", "Buscar", ayuda="Placa, serial, quien recibe, cédula o área."))

    def obtener_filas(self, valores, usuario=None):
        hoy = hoy_colombia()
        consulta = AsignacionEquipo.objects.filter(estado=AsignacionEquipo.Estado.ASIGNADO).select_related(
            "equipo", "funcionario")
        if valores["tipo"]:
            consulta = consulta.filter(equipo__tipo=valores["tipo"])
        filas = []
        for a in consulta:
            fila = {
                "placa": a.equipo.placa, "tipo": ETIQUETA_TIPO.get(a.equipo.tipo, a.equipo.tipo),
                "equipo": f"{a.equipo.marca} {a.equipo.modelo}".strip(), "serial": a.equipo.serial,
                "recibe": _recibe(a), "cedula": _cedula(a), "area": a.area, "accesorios": a.accesorios,
                "fecha": a.fecha_entrega, "dias": _dias_desde(a.fecha_entrega, hoy),
            }
            if valores["q"] and not any(contiene(fila[k], valores["q"])
                                        for k in ("placa", "serial", "recibe", "cedula", "area")):
                continue
            filas.append(fila)
        filas.sort(key=lambda f: (f["recibe"].lower(), f["placa"]))
        return filas

    def resumen(self, filas):
        return [("Equipos entregados", len(filas)), ("Personas", len({f["recibe"] for f in filas}))]


class EquiposHistorialEntregas(Informe):
    clave = "equipos_historial_entregas"
    titulo = "Historial de entregas y devoluciones de equipos"
    categoria = CATEGORIA
    descripcion = "Todas las entregas de computadores y otros equipos por rango de fechas."
    columnas = (
        Columna("fecha", "Entrega", 1.3, "der"), Columna("placa", "Placa", 1), Columna("tipo", "Tipo", 1),
        Columna("recibe", "Recibe", 2), Columna("cedula", "Cédula", 1.1), Columna("area", "Área", 1.8),
        Columna("entregado_por", "Entregó", 1.3), Columna("estado", "Estado", 1, "centro", tono=True),
        Columna("devolucion", "Devolución", 1.3, "der"), Columna("recibido_por", "Recibió", 1.3),
    )
    columnas_pdf = ("fecha", "placa", "tipo", "recibe", "area", "estado", "devolucion")
    filtros = (
        Filtro("desde", "Entregado desde", "date"), Filtro("hasta", "Entregado hasta", "date"),
        Filtro("tipo", "Tipo de equipo", "select", opciones_con_todos(Equipo.Tipo.choices)),
        Filtro("estado", "Estado", "select", opciones_con_todos(AsignacionEquipo.Estado.choices)),
        Filtro("q", "Buscar", ayuda="Placa, quien recibe, cédula o área."),
    )

    def obtener_filas(self, valores, usuario=None):
        consulta = AsignacionEquipo.objects.select_related("equipo", "funcionario", "entregado_por", "recibido_por")
        if valores["desde"]:
            consulta = consulta.filter(fecha_entrega__date__gte=valores["desde"])
        if valores["hasta"]:
            consulta = consulta.filter(fecha_entrega__date__lte=valores["hasta"])
        if valores["tipo"]:
            consulta = consulta.filter(equipo__tipo=valores["tipo"])
        if valores["estado"]:
            consulta = consulta.filter(estado=valores["estado"])
        filas = []
        for a in consulta:
            fila = {
                "fecha": a.fecha_entrega, "placa": a.equipo.placa,
                "tipo": ETIQUETA_TIPO.get(a.equipo.tipo, a.equipo.tipo), "recibe": _recibe(a),
                "cedula": _cedula(a), "area": a.area, "entregado_por": _usuario(a.entregado_por),
                "estado": a.get_estado_display(), "devolucion": a.fecha_devolucion,
                "recibido_por": _usuario(a.recibido_por),
            }
            if valores["q"] and not any(contiene(fila[k], valores["q"])
                                        for k in ("placa", "recibe", "cedula", "area")):
                continue
            filas.append(fila)
        return filas

    def resumen(self, filas):
        return [("Entregas", len(filas)),
                ("Vigentes", sum(1 for f in filas if f["estado"] == "Asignado")),
                ("Devueltas", sum(1 for f in filas if f["estado"] == "Devuelto"))]


INFORMES = [RadiosEntregados(), RadiosHistorialEntregas(), EntregasSinFirma(),
            TransferenciasComponentes(), EquiposEntregados(), EquiposHistorialEntregas()]
