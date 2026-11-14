"""Funciones pequeñas que comparten los informes."""
import re
import unicodedata

OPCIONES_ACTIVO = (
    ("activos", "En servicio"), ("bajas", "Dados de baja"), ("todos", "Todos"),
)

__all__ = [
    "OPCIONES_ACTIVO", "aplicar_activo", "clave_placa", "contiene", "dias_entre",
    "opciones_con_todos", "ordenar_por_placa", "texto_componente",
]


def opciones_con_todos(opciones, etiqueta="Todos"):
    """Agrega la opción "Todos" (valor vacío) al inicio de una lista de opciones."""
    return (("", etiqueta),) + tuple((str(v), e) for v, e in opciones)


def aplicar_activo(consulta, valor, campo="activo"):
    """Filtra por estado: "activos", "bajas" o cualquier otro valor para todos."""
    if valor == "activos":
        return consulta.filter(**{campo: True})
    if valor == "bajas":
        return consulta.filter(**{campo: False})
    return consulta


def _simple(texto):
    """Texto en minúsculas y sin tildes, para comparar."""
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def contiene(valor, buscado):
    """¿'valor' contiene 'buscado'? Sin importar mayúsculas ni tildes."""
    return _simple(buscado).strip() in _simple(valor)


def dias_entre(fecha, hoy):
    """Días desde hoy hasta 'fecha' (negativo = ya pasó). None si no hay fecha."""
    return None if fecha is None else (fecha - hoy).days


def clave_placa(placa):
    """Orden natural: RJ-2 antes que RJ-10."""
    texto = str(placa or "")
    partes = re.split(r"(\d+)", texto.upper())
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in partes if p != ""]


def ordenar_por_placa(filas, campo="placa"):
    """Ordena las filas por placa en orden natural (JN-2 antes que JN-10)."""
    return sorted(filas, key=lambda f: clave_placa(f.get(campo)))


def texto_componente(c):
    """Texto de un componente de alarma ("2 sensores") o el texto tal cual."""
    if isinstance(c, dict):
        nombre = c.get("nombre", "")
        cantidad = c.get("cantidad", 1)
        return f"{cantidad} {nombre}" if cantidad and cantidad > 1 else nombre
    return str(c)
