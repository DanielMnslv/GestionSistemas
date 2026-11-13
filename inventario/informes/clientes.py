"""Informes de clientes y puestos."""

from ..models import AsignacionRadio, Cliente, Puesto, Radio
from .ayudas import contiene
from .base import Columna, Filtro, Informe

CATEGORIA = "Clientes y puestos"
OPCIONES_ESTADO_PERSONA = (("activos", "Activos"), ("inactivos", "Inactivos"), ("todos", "Todos"))


def _normal(texto):
    return " ".join((texto or "").lower().split())


class ClientesPuestos(Informe):
    clave = "clientes_puestos"
    titulo = "Clientes y puestos de servicio"
    categoria = CATEGORIA
    descripcion = "Cada puesto con su cliente, sede y cuántos radios tiene asignados."
    columnas = (
        Columna("cliente", "Cliente", 2.5), Columna("nit", "NIT", 1.1), Columna("sede", "Sede", 2),
        Columna("puesto", "Puesto", 2.5), Columna("estado", "Estado", 1, "centro", tono=True),
        Columna("radios", "Radios (por nombre)", 1, "der"),
    )
    orientacion = "vertical"
    filtros = (Filtro("estado", "Estado", "select", OPCIONES_ESTADO_PERSONA, inicial="activos"),
               Filtro("q", "Buscar", ayuda="Cliente, sede o puesto."))

    def obtener_filas(self, valores, usuario=None):
        radios_por_puesto = {}
        for cliente, puesto in Radio.objects.filter(activo=True).exclude(puesto_asignado="").values_list(
                "cliente_asignado", "puesto_asignado"):
            clave = (_normal(cliente), _normal(puesto))
            radios_por_puesto[clave] = radios_por_puesto.get(clave, 0) + 1
        consulta = Puesto.objects.select_related("cliente")
        if valores["estado"] == "activos":
            consulta = consulta.filter(activo=True, cliente__activo=True)
        elif valores["estado"] == "inactivos":
            consulta = consulta.exclude(activo=True, cliente__activo=True)
        filas = []
        for p in consulta:
            fila = {
                "cliente": p.cliente.nombre, "nit": p.cliente.nit, "sede": p.sede, "puesto": p.nombre,
                "estado": "Activo" if p.activo and p.cliente.activo else "Inactivo",
                "radios": radios_por_puesto.get((_normal(p.cliente.nombre), _normal(p.nombre)), 0),
            }
            if valores["q"] and not any(contiene(fila[k], valores["q"]) for k in ("cliente", "sede", "puesto")):
                continue
            filas.append(fila)
        filas.sort(key=lambda f: (f["cliente"].lower(), f["sede"].lower(), f["puesto"].lower()))
        return filas

    def resumen(self, filas):
        return [("Puestos", len(filas)), ("Clientes", len({f["cliente"] for f in filas})),
                ("Puestos sin radio", sum(1 for f in filas if not f["radios"]))]


class ClientesResumen(Informe):
    clave = "clientes_resumen"
    titulo = "Clientes: puestos y radios"
    categoria = CATEGORIA
    descripcion = "Una línea por cliente con su número de puestos y de radios en uso."
    columnas = (
        Columna("cliente", "Cliente", 3), Columna("nit", "NIT", 1.2),
        Columna("estado", "Estado", 1, "centro", tono=True), Columna("puestos", "Puestos activos", 1, "der"),
        Columna("radios", "Radios", 1, "der"),
    )
    orientacion = "vertical"
    filtros = (Filtro("estado", "Estado", "select", OPCIONES_ESTADO_PERSONA, inicial="activos"),)

    def obtener_filas(self, valores, usuario=None):
        radios = {}
        for cliente in Radio.objects.filter(activo=True).exclude(cliente_asignado="").values_list(
                "cliente_asignado", flat=True):
            radios[_normal(cliente)] = radios.get(_normal(cliente), 0) + 1
        consulta = Cliente.objects.all()
        if valores["estado"] == "activos":
            consulta = consulta.filter(activo=True)
        elif valores["estado"] == "inactivos":
            consulta = consulta.filter(activo=False)
        puestos = {}
        for cliente_id in Puesto.objects.filter(activo=True).values_list("cliente_id", flat=True):
            puestos[cliente_id] = puestos.get(cliente_id, 0) + 1
        return [{
            "cliente": c.nombre, "nit": c.nit, "estado": "Activo" if c.activo else "Inactivo",
            "puestos": puestos.get(c.pk, 0), "radios": radios.get(_normal(c.nombre), 0),
        } for c in consulta.order_by("nombre")]

    def resumen(self, filas):
        return [("Clientes", len(filas)), ("Puestos", sum(f["puestos"] for f in filas)),
                ("Radios", sum(f["radios"] for f in filas))]


INFORMES = [ClientesPuestos(), ClientesResumen()]
