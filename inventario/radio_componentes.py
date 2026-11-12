import json


COMPONENTES_TRANSFERIBLES_RADIO = (
    ("base", "Base", "base", "estado_base"),
    ("cargador", "Cargador", "cargador", "estado_cargador"),
    ("antena", "Antena", "antena", "estado_antena"),
    ("baterias", "Baterías", None, "estado_baterias"),
    (
        "perilla_encendido", "Perilla de encendido",
        "perilla_encendido", "estado_perilla_encendido",
    ),
    (
        "perilla_frecuencia", "Perilla de frecuencia",
        "perilla_frecuencia", "estado_perilla_frecuencia",
    ),
    ("clip", "Clip", "clip", "estado_clip"),
)


def _cantidad_baterias(radio):
    return sum(
        getattr(radio, campo) is True
        for campo in ("bateria_1", "bateria_2")
    )


def componentes_presentes_radio(radio):
    presentes = []
    for clave, nombre, campo, campo_estado in COMPONENTES_TRANSFERIBLES_RADIO:
        if clave == "baterias":
            cantidad = _cantidad_baterias(radio)
        elif getattr(radio, campo) is True:
            cantidad = 1
        else:
            continue
        if cantidad:
            presentes.append({
                "clave": clave,
                "nombre": nombre,
                "cantidad": cantidad,
                "estado": getattr(radio, campo_estado) or "",
            })
    return presentes


def componentes_faltantes_radio(origen, destino):
    faltantes = []
    for componente in componentes_presentes_radio(origen):
        if componente["clave"] == "baterias":
            cantidad = min(
                componente["cantidad"], 2 - _cantidad_baterias(destino)
            )
        else:
            campo = next(
                dato[2] for dato in COMPONENTES_TRANSFERIBLES_RADIO
                if dato[0] == componente["clave"]
            )
            cantidad = 0 if getattr(destino, campo) is True else 1
        if cantidad > 0:
            faltantes.append({**componente, "cantidad": cantidad})
    return faltantes


def destinos_radio_para_transferencia(origen, radios_activos):
    destinos = []
    if not origen.activo:
        return destinos
    for destino in radios_activos:
        if destino.pk == origen.pk:
            continue
        componentes = componentes_faltantes_radio(origen, destino)
        if componentes:
            destinos.append({
                "radio": destino,
                "componentes_json": json.dumps(
                    [
                        {
                            "nombre": componente["nombre"],
                            "cantidad": componente["cantidad"],
                        }
                        for componente in componentes
                    ],
                    ensure_ascii=False,
                ),
            })
    return destinos
