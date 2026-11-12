"""Color con el que se muestra un estado (Bueno, Regular, Dañado, No tiene...)."""


def tono_estado(texto):
    t = (texto or "").lower()
    if any(p in t for p in ("bueno", "operativ", "excelente", "nuevo")):
        return "green"
    if any(p in t for p in ("malo", "dañ", "defect", "falla", "no funciona", "baja")):
        return "red"
    if any(p in t for p in ("regular", "desgast", "revis")):
        return "amber"
    return "gray"
