"""Catálogo de informes disponibles, agrupado por categoría."""
from . import (
    clientes, entregas, equipos, historial, mantenimiento, radios,
    resumen_general, seguridad,
)

ORDEN_CATEGORIAS = [
    "General",
    "Equipos de TI",
    "Radios",
    "Mantenimiento",
    "Entregas",
    "Seguridad informática",
    "Clientes y vigilantes",
]


def _todos():
    lista = [resumen_general.INFORME]
    for modulo in (equipos, radios, mantenimiento, entregas, seguridad, clientes):
        lista.extend(modulo.INFORMES)
    lista.append(historial.INFORME)
    return lista


INFORMES = _todos()
_POR_CLAVE = {i.clave: i for i in INFORMES}
assert len(_POR_CLAVE) == len(INFORMES), "Hay claves de informe repetidas"


def obtener_informe(clave):
    return _POR_CLAVE[clave]  # KeyError si no existe


def informes_por_categoria():
    grupos = {}
    for informe in INFORMES:
        grupos.setdefault(informe.categoria, []).append(informe)
    orden = [c for c in ORDEN_CATEGORIAS if c in grupos]
    orden += [c for c in grupos if c not in orden]
    return [(c, grupos[c]) for c in orden]
