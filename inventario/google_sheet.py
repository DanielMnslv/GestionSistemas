"""Lectura del Google Sheet "CONTROL DE MANTENIMIENTO DE EQUIPOS".

Lo comparten los comandos que importan radios y asignaciones desde el
Sheet.
"""
import re
import tempfile
import unicodedata
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import openpyxl
from django.core.management.base import CommandError


SHEET_ID = "1-gpRUMUNQ6TcWxa4vjmHGHpRLpsshir02uf39zf_6RA"
# Se descarga el libro completo en .xlsx: la exportación CSV de Google
# infiere tipos por columna y descarta valores (por ejemplo, Versión).
URL_EXPORTACION = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
)


def normalizar_serial(valor):
    """Llave de cruce: mayúsculas, sin espacios ni símbolos."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).upper()
    if re.search(r"NO SE VE|SIN SERIAL|NO TIENE|ILEGIBLE", texto):
        return ""
    if texto.strip() in ("N/A", "NA", "0"):
        return ""
    return re.sub(r"[^A-Z0-9]", "", texto)


def normalizar_placa(valor):
    return re.sub(r"\s+", "", texto_celda(valor)).upper()


def clave_placa(valor):
    """Letras y número de la placa: RJ-093, RJ93 -> RJ-93; PC-01 y PC--01
    -> PC-1. Solo sirve como respaldo: hay placas distintas que difieren
    únicamente en los ceros (RJ-014 y RJ-14)."""
    placa = normalizar_placa(valor)
    partes = re.fullmatch(r"([A-Z]+)[-_]*0*(\d+)", placa)
    return f"{partes.group(1)}-{int(partes.group(2))}" if partes else placa


def texto_celda(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return re.sub(r"\s+", " ", str(valor)).strip()


def normalizar_encabezado(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().casefold()


@contextmanager
def libro_del_sheet(archivo=None, stdout=None):
    """Entrega la ruta del .xlsx: el archivo dado o una descarga temporal."""
    if archivo:
        archivo = Path(archivo)
        if not archivo.is_file():
            raise CommandError(f"No se encontró el archivo: {archivo}")
        yield archivo
        return

    with tempfile.TemporaryDirectory() as carpeta:
        destino = Path(carpeta) / "control_mantenimiento.xlsx"
        if stdout:
            stdout.write("Descargando el Google Sheet…")
        try:
            urllib.request.urlretrieve(URL_EXPORTACION, destino)
        except OSError as error:
            raise CommandError(f"No se pudo descargar el Sheet: {error}")
        yield destino


def leer_hoja(archivo, hoja, columnas):
    """Lee las columnas pedidas de una hoja.

    Devuelve una lista de diccionarios {columna: valor} con la clave
    "_fila" (número de fila en el Sheet). Los encabezados se comparan sin
    tildes ni mayúsculas, porque en el Sheet varían.
    """
    libro = openpyxl.load_workbook(archivo, read_only=True, data_only=True)
    try:
        if hoja not in libro.sheetnames:
            raise CommandError(f"No existe la hoja {hoja}.")
        iterador = libro[hoja].iter_rows(values_only=True)
        encabezados = next(iterador, None)
        if not encabezados:
            raise CommandError(f"La hoja {hoja} está vacía.")

        posiciones = {
            normalizar_encabezado(v): i
            for i, v in enumerate(encabezados) if v is not None
        }
        indices = {}
        faltantes = []
        for columna in columnas:
            clave = normalizar_encabezado(columna)
            if clave in posiciones:
                indices[columna] = posiciones[clave]
            else:
                faltantes.append(columna)
        if faltantes:
            raise CommandError(
                f"Faltan columnas en {hoja}: " + ", ".join(faltantes)
            )

        filas = []
        for numero, fila in enumerate(iterador, start=2):
            if not any(v is not None and str(v).strip() for v in fila):
                continue
            datos = {
                columna: fila[i] if i < len(fila) else None
                for columna, i in indices.items()
            }
            datos["_fila"] = numero
            filas.append(datos)
        return filas
    finally:
        libro.close()
