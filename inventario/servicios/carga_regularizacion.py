
from django.db import transaction
from django.db.models import Q

from inventario.models import (
    Equipo,
    AsignacionEquipo,
    AsignacionRadio,
    RegularizacionInventario,
    ItemRegularizacionInventario,
)


class ErrorCargaRegularizacion(Exception):
    """Error controlado durante la creación de una regularización."""


ESTADOS_PROCESO_ABIERTO = [
    RegularizacionInventario.Estado.BORRADOR,
    RegularizacionInventario.Estado.EN_RECUPERACION,
]


def _texto(valor):
    """Normaliza valores de texto sin modificar su contenido original."""
    return str(valor or "").strip()


def _nombre_equipo(asignacion, equipo):
    """
    Obtiene el nombre del receptor.

    Prioridad:
    1. Nombre del funcionario relacionado.
    2. Nombre histórico guardado en la asignación.
    3. Nombre registrado actualmente en el equipo.
    """

    if asignacion.funcionario_id:
        nombre = _texto(asignacion.funcionario.nombre_completo)

        if nombre:
            return nombre

    nombre = _texto(asignacion.nombre_recibe)

    if nombre:
        return nombre

    return _texto(equipo.responsable_nombre)


def _validar_cedulas_asignacion(asignacion, cedula):
    """
    Comprueba que la asignación corresponda a la cédula solicitada.

    Si existen dos cédulas en la asignación, ambas deben coincidir.
    """

    cedula_proceso = _texto(cedula)
    cedula_receptor = _texto(asignacion.cedula_recibe)

    cedula_funcionario = ""

    if asignacion.funcionario_id:
        cedula_funcionario = _texto(
            asignacion.funcionario.cedula
        )

    if (
        cedula_receptor
        and cedula_funcionario
        and cedula_receptor != cedula_funcionario
    ):
        raise ErrorCargaRegularizacion(
            "La asignación de equipo ID "
            f"{asignacion.pk} tiene cédulas contradictorias: "
            f"receptor={cedula_receptor}, "
            f"funcionario={cedula_funcionario}."
        )

    if cedula_proceso not in (
        cedula_receptor,
        cedula_funcionario,
    ):
        raise ErrorCargaRegularizacion(
            "La asignación de equipo ID "
            f"{asignacion.pk} no corresponde a la cédula "
            "de la regularización."
        )


def _registrar_candidato(
    items,
    equipo,
    origen,
    asignacion_radio=None,
    asignacion_equipo=None,
    responsable_nombre="",
    responsable_cedula="",
    cedula_radio="",
    ubicacion="",
    cliente="",
    puesto="",
    coordinador="",
):
    """
    Registra un equipo sin permitir duplicados silenciosos.

    Si el mismo equipo aparece asociado a dos orígenes diferentes,
    se detiene la carga para evitar seleccionar una asignación
    arbitrariamente.
    """

    equipo_id = equipo.pk

    if equipo_id in items:
        anterior = items[equipo_id]

        raise ErrorCargaRegularizacion(
            f"El equipo ID {equipo_id}, placa {equipo.placa}, "
            "aparece asociado a más de un origen. "
            f"Origen encontrado: {anterior['origen']}; "
            f"nuevo origen: {origen}. "
            "Se requiere verificar sus asignaciones antes de cargarlo."
        )

    items[equipo_id] = {
        "equipo": equipo,
        "origen": origen,
        "asignacion_radio": asignacion_radio,
        "asignacion_equipo": asignacion_equipo,
        "responsable_nombre": _texto(responsable_nombre),
        "responsable_cedula": _texto(responsable_cedula),
        "cedula_radio": _texto(cedula_radio),
        "ubicacion": _texto(ubicacion),
        "cliente": _texto(cliente),
        "puesto": _texto(puesto),
        "coordinador": _texto(coordinador),
    }


def _construir_items(cedula):
    """
    Identifica activos asociados a una cédula.

    Orígenes:
    1. Asignaciones activas de radio.
    2. Asignaciones formales activas de equipo.
    3. Responsable directo del equipo.

    No permite duplicados ni conflictos de asignación.
    """

    items = {}

    # ---------------------------------------------------------
    # 1. RADIOS CON ASIGNACIÓN ACTIVA
    # ---------------------------------------------------------

    asignaciones_radio = (
        AsignacionRadio.objects
        .filter(
            estado=AsignacionRadio.Estado.ASIGNADO,
            cedula_funcionario=cedula,
            radio__equipo__isnull=False,
        )
        .select_related(
            "radio",
            "radio__equipo",
        )
        .order_by("id")
    )

    for asignacion in asignaciones_radio:

        radio = asignacion.radio
        equipo = radio.equipo

        if not equipo:
            raise ErrorCargaRegularizacion(
                f"La asignación de radio ID {asignacion.pk} "
                "no tiene un equipo relacionado."
            )

        if not equipo.activo:
            raise ErrorCargaRegularizacion(
                f"El radio ID {radio.pk}, vinculado al equipo "
                f"{equipo.placa}, tiene una asignación activa "
                "pero su equipo está inactivo."
            )

        _registrar_candidato(
            items=items,
            equipo=equipo,
            origen=ItemRegularizacionInventario.Origen.RADIO,
            asignacion_radio=asignacion,
            responsable_nombre=equipo.responsable_nombre,
            responsable_cedula=equipo.responsable_cedula,
            cedula_radio=asignacion.cedula_funcionario,
            ubicacion=equipo.ubicacion,
            cliente=asignacion.cliente_asignado,
            puesto=asignacion.puesto_asignado,
            coordinador=asignacion.coordinador_zona,
        )

    # ---------------------------------------------------------
    # 2. EQUIPOS CON ASIGNACIÓN FORMAL ACTIVA
    # ---------------------------------------------------------

    asignaciones_equipo = (
        AsignacionEquipo.objects
        .filter(
            estado=AsignacionEquipo.Estado.ASIGNADO,
        )
        .filter(
            Q(cedula_recibe=cedula)
            | Q(funcionario__cedula=cedula)
        )
        .select_related(
            "equipo",
            "funcionario",
        )
        .order_by("id")
    )

    for asignacion in asignaciones_equipo:

        equipo = asignacion.equipo

        _validar_cedulas_asignacion(
            asignacion,
            cedula,
        )

        if not equipo.activo:
            raise ErrorCargaRegularizacion(
                f"La asignación de equipo ID {asignacion.pk} "
                f"corresponde al equipo {equipo.placa}, "
                "pero el equipo está inactivo."
            )

        _registrar_candidato(
            items=items,
            equipo=equipo,
            origen=ItemRegularizacionInventario.Origen.EQUIPO,
            asignacion_equipo=asignacion,
            responsable_nombre=_nombre_equipo(
                asignacion,
                equipo,
            ),
            responsable_cedula=equipo.responsable_cedula,
            ubicacion=equipo.ubicacion,
        )

    # ---------------------------------------------------------
    # 3. EQUIPOS CON RESPONSABLE DIRECTO
    # ---------------------------------------------------------

    equipos_directos = (
        Equipo.objects
        .filter(
            activo=True,
            responsable_cedula=cedula,
        )
        .order_by("id")
    )

    for equipo in equipos_directos:

        # Si ya fue incorporado por una asignación de radio
        # o una asignación formal de equipo, no se duplica.
        if equipo.pk in items:
            continue

        # Un equipo con responsable directo no debe tener
        # asignaciones formales activas que no fueron incluidas
        # en esta regularización.
        asignacion_equipo_activa = (
            AsignacionEquipo.objects
            .filter(
                equipo_id=equipo.pk,
                estado=AsignacionEquipo.Estado.ASIGNADO,
            )
            .select_related("funcionario")
            .first()
        )

        asignacion_radio_activa = (
            AsignacionRadio.objects
            .filter(
                radio__equipo_id=equipo.pk,
                estado=AsignacionRadio.Estado.ASIGNADO,
            )
            .select_related("radio")
            .first()
        )

        if asignacion_equipo_activa:
            raise ErrorCargaRegularizacion(
                f"El equipo {equipo.placa} tiene responsable directo "
                f"{cedula}, pero también tiene una asignación "
                f"formal activa ID {asignacion_equipo_activa.pk} "
                "que no corresponde a esta cédula."
            )

        if asignacion_radio_activa:
            raise ErrorCargaRegularizacion(
                f"El equipo {equipo.placa} tiene responsable directo "
                f"{cedula}, pero también tiene una asignación "
                f"de radio activa ID {asignacion_radio_activa.pk} "
                "que no fue incluida por la cédula solicitada."
            )

        _registrar_candidato(
            items=items,
            equipo=equipo,
            origen=ItemRegularizacionInventario.Origen.DIRECTO,
            responsable_nombre=equipo.responsable_nombre,
            responsable_cedula=equipo.responsable_cedula,
            ubicacion=equipo.ubicacion,
        )

    return list(items.values())


# -------------------------------------------------------------
# CREAR REGULARIZACIÓN
# -------------------------------------------------------------

@transaction.atomic
def crear_regularizacion_inventario(
    cedula,
    usuario,
    nombre_origen="",
    observaciones="",
):
    """
    Crea una regularización independiente.

    No modifica:
    - Asignaciones originales.
    - Responsables actuales.
    - Ubicaciones.
    - Estados operativos de los equipos.
    """

    cedula = _texto(cedula)

    if not cedula:
        raise ErrorCargaRegularizacion(
            "Debe indicar la cédula de origen."
        )

    if not usuario or not usuario.is_authenticated:
        raise ErrorCargaRegularizacion(
            "Se requiere un usuario autenticado."
        )

    # Evitar crear más de un proceso abierto para la misma cédula.
    procesos_abiertos = (
        RegularizacionInventario.objects
        .filter(
            cedula_origen=cedula,
            estado__in=ESTADOS_PROCESO_ABIERTO,
        )
    )

    if procesos_abiertos.exists():
        raise ErrorCargaRegularizacion(
            "Ya existe una regularización abierta para esta cédula."
        )

    # Construir candidatos y detectar inconsistencias.
    candidatos = _construir_items(cedula)

    if not candidatos:
        raise ErrorCargaRegularizacion(
            "No se encontraron activos asociados a esta cédula."
        )

    ids = sorted(
        candidato["equipo"].pk
        for candidato in candidatos
    )

    # Bloquear los equipos durante la creación.
    equipos_bloqueados = list(
        Equipo.objects
        .select_for_update()
        .filter(pk__in=ids)
        .order_by("pk")
    )

    if len(equipos_bloqueados) != len(ids):
        raise ErrorCargaRegularizacion(
            "Uno o más equipos dejaron de existir."
        )

    # Verificar que ningún equipo esté en otra regularización abierta.
    existentes = list(
        ItemRegularizacionInventario.objects
        .filter(
            equipo_id__in=ids,
            regularizacion__estado__in=ESTADOS_PROCESO_ABIERTO,
        )
        .values_list(
            "equipo_id",
            flat=True,
        )
    )

    if existentes:
        raise ErrorCargaRegularizacion(
            "Hay activos incluidos en otra regularización abierta. "
            f"IDs de equipos: {sorted(set(existentes))}"
        )

    # Crear encabezado.
    regularizacion = RegularizacionInventario.objects.create(
        cedula_origen=cedula,
        nombre_origen=_texto(nombre_origen),
        estado=RegularizacionInventario.Estado.BORRADOR,
        observaciones=_texto(observaciones),
        creado_por=usuario,
    )

    # Crear los elementos sin modificar los activos originales.
    for datos in candidatos:

        equipo = datos["equipo"]

        item = ItemRegularizacionInventario(
            regularizacion=regularizacion,
            equipo=equipo,
            origen=datos["origen"],

            asignacion_radio=datos["asignacion_radio"],
            asignacion_equipo=datos["asignacion_equipo"],

            placa_origen=_texto(equipo.placa),
            serial_origen=_texto(equipo.serial),

            responsable_nombre_origen=(
                datos["responsable_nombre"]
            ),
            responsable_cedula_origen=(
                datos["responsable_cedula"]
            ),

            cedula_radio_origen=(
                datos["cedula_radio"]
            ),

            ubicacion_origen=datos["ubicacion"],
            cliente_origen=datos["cliente"],
            puesto_origen=datos["puesto"],
            coordinador_origen=datos["coordinador"],

            resultado=(
                ItemRegularizacionInventario.Resultado.PENDIENTE
            ),
        )

        item.save()

    return regularizacion
