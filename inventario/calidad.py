"""Reglas de la pantalla «Calidad de datos».

Detecta los registros que no cuadran con la realidad y que la pantalla
ayuda a corregir uno por uno:

- Equipos con responsable escrito pero sin entrega registrada.
- Entregas vigentes sin firma dibujada en JANO (solo enlace de Google o nada).
- Entregas de radios sin puesto del catálogo de clientes.
- Funcionarios activos sin correo.
- Equipos sin estado operativo que se pueden completar con su mantenimiento.

Aquí solo hay consultas y la lógica para aplicar correcciones; las vistas
están en ``views_calidad.py``.
"""

import csv
import difflib
import io
import re
import unicodedata

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q

from .models import (
    AsignacionEquipo,
    AsignacionRadio,
    Cliente,
    Equipo,
    Funcionario,
    Puesto,
)


def normalizar(texto):
    """Texto en mayúsculas, sin tildes ni signos, para comparar nombres escritos distinto."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", texto).strip()


# ---------------------------------------------------------------- Entregas

def equipos_sin_entrega():
    """Equipos activos (no radios) con responsable escrito y sin entrega vigente.

    Suelen venir del Sheet: se sabe quién los tiene, pero no hay acta.
    """
    vigente = AsignacionEquipo.objects.filter(
        equipo=OuterRef("pk"), estado=AsignacionEquipo.Estado.ASIGNADO
    )
    return (
        Equipo.objects.filter(activo=True)
        .exclude(tipo=Equipo.Tipo.RADIO)
        .exclude(responsable_nombre="")
        .annotate(con_entrega=Exists(vigente))
        .filter(con_entrega=False)
        .order_by("tipo", "placa")
    )


def parece_baja(texto):
    """Indica si el responsable escrito dice que el equipo se dio de baja o se perdió.

    En el Sheet se anotaba «BAJA 2025», «BAJA ROBADO» o el nombre seguido de
    «baja»: esos equipos no se entregan, se revisan y se dan de baja.
    """
    return bool(re.search(r"\bBAJA\b|\bROBAD[OA]\b", normalizar(texto)))


def funcionario_de(equipo):
    """Funcionario activo con la cédula del responsable del equipo, o None."""
    cedula = (equipo.responsable_cedula or "").strip()
    if not cedula:
        return None
    return Funcionario.objects.filter(cedula=cedula, activo=True).first()


def entregas_sin_firma():
    """Entregas vigentes de equipos sin firma dibujada en JANO."""
    return (
        AsignacionEquipo.objects.filter(
            estado=AsignacionEquipo.Estado.ASIGNADO, firma="",
            equipo__activo=True,
        )
        .select_related("equipo", "funcionario")
        .order_by("nombre_recibe", "equipo__placa")
    )


# ------------------------------------------------------- Radios y puestos

def grupos_radios_sin_puesto():
    """Entregas vigentes de radios sin puesto del catálogo, agrupadas por texto.

    Devuelve una lista de diccionarios con ``clave`` (cliente|puesto
    normalizados), los textos tal como se escribieron, el número de radios y
    el cliente sugerido del catálogo (o None).
    """
    grupos = {}
    for entrega in AsignacionRadio.objects.filter(
        estado=AsignacionRadio.Estado.ASIGNADO, puesto__isnull=True
    ).only("cliente_asignado", "puesto_asignado"):
        clave = f"{normalizar(entrega.cliente_asignado)}|{normalizar(entrega.puesto_asignado)}"
        grupo = grupos.setdefault(clave, {
            "clave": clave,
            "cliente": entrega.cliente_asignado,
            "puesto": entrega.puesto_asignado,
            "radios": 0,
        })
        grupo["radios"] += 1
    clientes = _clientes_normalizados()
    resultado = sorted(grupos.values(), key=lambda g: (-g["radios"], g["cliente"]))
    for grupo in resultado:
        grupo["sugerido"] = sugerir_cliente(grupo["cliente"], clientes)
    return resultado


def _clientes_normalizados():
    """{nombre normalizado: cliente} de los clientes activos."""
    return {normalizar(c.nombre): c for c in Cliente.objects.filter(activo=True)}


def sugerir_cliente(texto, clientes=None):
    """Cliente del catálogo que más se parece al texto escrito, o None.

    Primero busca coincidencia exacta, luego que uno contenga al otro
    ("BACAO" y "BACAO SAS") y por último el nombre más parecido.
    """
    clientes = clientes if clientes is not None else _clientes_normalizados()
    buscado = normalizar(texto)
    if not buscado:
        return None
    if buscado in clientes:
        return clientes[buscado]
    contiene = sorted(
        (nombre for nombre in clientes if buscado in nombre or nombre in buscado),
        key=len,
    )
    if contiene:
        return clientes[contiene[0]]
    parecido = difflib.get_close_matches(buscado, list(clientes), n=1, cutoff=0.75)
    return clientes[parecido[0]] if parecido else None


def puestos_ordenados(cliente, texto_puesto):
    """Puestos activos del cliente, del más parecido al texto escrito al menos parecido."""
    buscado = normalizar(texto_puesto)

    def parecido(puesto):
        return difflib.SequenceMatcher(
            None, buscado, normalizar(f"{puesto.nombre} {puesto.sede}")
        ).ratio()

    return sorted(Puesto.objects.filter(cliente=cliente, activo=True), key=parecido, reverse=True)


def entregas_del_grupo(clave):
    """Entregas vigentes sin puesto cuyo cliente|puesto normalizado es ``clave``."""
    return [
        entrega for entrega in AsignacionRadio.objects.filter(
            estado=AsignacionRadio.Estado.ASIGNADO, puesto__isnull=True
        ).select_related("radio")
        if f"{normalizar(entrega.cliente_asignado)}|{normalizar(entrega.puesto_asignado)}" == clave
    ]


@transaction.atomic
def vincular_puesto(clave, puesto):
    """Asigna el puesto del catálogo a todas las entregas del grupo.

    Copia el nombre del cliente y del puesto del catálogo en la entrega y en
    el radio, igual que una entrega nueva hecha con el catálogo. Devuelve el
    número de entregas vinculadas.
    """
    cliente_texto = puesto.cliente.nombre[:200]
    puesto_texto = str(puesto)[:200]
    entregas = entregas_del_grupo(clave)
    for entrega in entregas:
        radio = entrega.radio
        # El radio copia el destino solo si todavía muestra el de esta entrega.
        if (radio.cliente_asignado, radio.puesto_asignado) == (
            entrega.cliente_asignado, entrega.puesto_asignado
        ):
            radio.cliente_asignado = cliente_texto
            radio.puesto_asignado = puesto_texto
            radio.save(update_fields=["cliente_asignado", "puesto_asignado", "actualizado_en"])
        entrega.puesto = puesto
        entrega.cliente_asignado = cliente_texto
        entrega.puesto_asignado = puesto_texto
        entrega.save(update_fields=[
            "puesto", "cliente_asignado", "puesto_asignado", "actualizado_en",
        ])
    return len(entregas)


# ----------------------------------------------------- Correos y estados

def funcionarios_sin_correo():
    """Funcionarios activos sin correo, con cuántos equipos tienen entregados."""
    return (
        Funcionario.objects.filter(activo=True, correo="")
        .annotate(equipos=Count(
            "asignaciones",
            filter=Q(asignaciones__estado=AsignacionEquipo.Estado.ASIGNADO),
        ))
        .order_by("nombre_completo")
    )


def correo_valido(correo):
    """El correo en minúsculas si es válido; si no, None."""
    correo = (correo or "").strip().lower()
    try:
        validate_email(correo)
    except ValidationError:
        return None
    return correo


def leer_archivo_correos(archivo):
    """Lee un Excel (.xlsx) o CSV con columnas de cédula y correo.

    Las columnas se buscan por su encabezado (que contenga "cedula" o
    "documento", y "correo" o "email"), en cualquier orden. Devuelve una
    lista de pares (cédula, correo) como texto.

    Raises:
        ValueError: si el formato no es válido o faltan las columnas.
    """
    nombre = (archivo.name or "").lower()
    if nombre.endswith(".xlsx"):
        from openpyxl import load_workbook

        try:
            libro = load_workbook(archivo, read_only=True, data_only=True)
        except Exception as error:  # Archivo dañado o no es Excel.
            raise ValueError("No se pudo leer el Excel.") from error
        filas = [
            ["" if c is None else str(c) for c in fila]
            for fila in libro.active.iter_rows(values_only=True)
        ]
    elif nombre.endswith(".csv"):
        texto = archivo.read().decode("utf-8-sig", errors="replace")
        separador = ";" if texto.count(";") > texto.count(",") else ","
        filas = list(csv.reader(io.StringIO(texto), delimiter=separador))
    else:
        raise ValueError("Sube un archivo Excel (.xlsx) o CSV.")

    for indice, fila in enumerate(filas[:10]):
        encabezados = [normalizar(c) for c in fila]
        col_cedula = next((i for i, c in enumerate(encabezados) if "CEDULA" in c or "DOCUMENTO" in c), None)
        col_correo = next((i for i, c in enumerate(encabezados) if "CORREO" in c or "EMAIL" in c), None)
        if col_cedula is not None and col_correo is not None:
            break
    else:
        raise ValueError("El archivo debe tener columnas «Cédula» y «Correo».")

    pares = []
    for fila in filas[indice + 1:]:
        if max(col_cedula, col_correo) >= len(fila):
            continue
        cedula = re.sub(r"\D", "", str(fila[col_cedula]).split(".")[0])
        if cedula:
            pares.append((cedula, str(fila[col_correo]).strip()))
    return pares


def aplicar_correos(pares):
    """Guarda los correos de los funcionarios activos que aún no tienen.

    No cambia correos ya registrados (eso se hace en la ficha de la persona).
    Devuelve un resumen con las cédulas actualizadas, no encontradas,
    inválidas y las que ya tenían correo.
    """
    resumen = {"actualizados": 0, "no_encontrados": [], "invalidos": [], "ya_tenian": 0}
    for cedula, correo in pares:
        funcionario = Funcionario.objects.filter(cedula=cedula, activo=True).first()
        if funcionario is None:
            resumen["no_encontrados"].append(cedula)
            continue
        valido = correo_valido(correo)
        if valido is None:
            if correo:
                resumen["invalidos"].append(cedula)
            continue
        if funcionario.correo:
            resumen["ya_tenian"] += 1
            continue
        funcionario.correo = valido
        funcionario.save(update_fields=["correo", "actualizado_en"])
        resumen["actualizados"] += 1
    return resumen


def equipos_sin_estado():
    """Equipos activos sin estado operativo (los radios usan su propio estado)."""
    return Equipo.objects.filter(activo=True, estado_operativo="").filter(
        Q(radio__isnull=True) | Q(radio__estado_radio="")
        | Q(radio__estado_radio__isnull=True)
    )


def completar_estados():
    """Completa el estado operativo con el último mantenimiento. Devuelve cuántos cambiaron."""
    return sum(
        1 for equipo in equipos_sin_estado().distinct()
        if equipo.actualizar_estado_operativo()
    )


def resumen():
    """Cuántos pendientes hay en cada sección (para las pestañas y el menú)."""
    return {
        "entregas": equipos_sin_entrega().count(),
        "firmas": entregas_sin_firma().count(),
        "puestos": AsignacionRadio.objects.filter(
            estado=AsignacionRadio.Estado.ASIGNADO, puesto__isnull=True
        ).count(),
        "correos": Funcionario.objects.filter(activo=True, correo="").count(),
        "estados": equipos_sin_estado().distinct().count(),
    }
