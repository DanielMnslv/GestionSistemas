
from django.db import transaction
from django.utils import timezone

from inventario.models import (
    Equipo,
    Radio,
    AsignacionEquipo,
    AsignacionRadio,
    ItemRegularizacionInventario,
)


UBICACION_BODEGA = "Bodega central JANO"


class RegularizacionError(Exception):
    """Error controlado durante la regularización."""


class RequiereVerificacion(Exception):
    """
    Se utiliza cuando los datos actuales no coinciden con los datos
    originales. Provoca la reversión completa de la recepción.
    """
    pass


def _texto(valor):
    """Normaliza valores de texto."""
    return str(valor or "").strip()


def _guardar_verificacion(item, motivo):
    """Guarda el resultado de verificación sin cerrar asignaciones."""

    item.resultado = ItemRegularizacionInventario.Resultado.VERIFICACION

    nota = f"Requiere verificación: {motivo}"
    observaciones_actuales = _texto(item.observaciones)

    if nota not in observaciones_actuales:
        item.observaciones = (
            f"{observaciones_actuales}\n{nota}".strip()
        )

    item.save(update_fields=[
        "resultado",
        "estado_fisico",
        "observaciones",
        "actualizado_en",
    ])


def _cerrar_asignacion_equipo(asignacion, usuario, observaciones):
    asignacion.estado = "DEVUELTO"
    asignacion.fecha_devolucion = timezone.now()
    asignacion.recibido_por = usuario
    asignacion.observaciones_devolucion = observaciones

    asignacion.save(update_fields=[
        "estado",
        "fecha_devolucion",
        "recibido_por",
        "observaciones_devolucion",
        "actualizado_en",
    ])


def _cerrar_asignacion_radio(asignacion, usuario, observaciones):
    asignacion.estado = "DEVUELTO"
    asignacion.fecha_devolucion = timezone.now()
    asignacion.recibido_por = usuario
    asignacion.observaciones_devolucion = observaciones

    asignacion.save(update_fields=[
        "estado",
        "fecha_devolucion",
        "recibido_por",
        "observaciones_devolucion",
        "actualizado_en",
    ])


def _responsable_coincide(equipo, item):
    """
    Comprueba que la cédula responsable del equipo siga siendo
    la registrada al iniciar la regularización.
    """

    cedula_actual = _texto(equipo.responsable_cedula)
    cedula_origen = _texto(item.responsable_cedula_origen)

    return cedula_actual == cedula_origen


def _validar_referencias_origen(item):
    """
    Comprueba que las referencias de asignación correspondan
    al origen registrado en el elemento.
    """

    if item.origen == ItemRegularizacionInventario.Origen.EQUIPO:

        if not item.asignacion_equipo_id or item.asignacion_radio_id:
            raise RequiereVerificacion(
                "Las referencias de asignación del equipo son inconsistentes."
            )

    elif item.origen == ItemRegularizacionInventario.Origen.RADIO:

        if not item.asignacion_radio_id or item.asignacion_equipo_id:
            raise RequiereVerificacion(
                "Las referencias de asignación del radio son inconsistentes."
            )

    elif item.origen == ItemRegularizacionInventario.Origen.DIRECTO:

        if item.asignacion_equipo_id or item.asignacion_radio_id:
            raise RequiereVerificacion(
                "Un activo de origen directo tiene referencias "
                "de asignación formal."
            )

    else:
        raise RegularizacionError(
            "El origen del activo no es reconocido."
        )


def _limpiar_responsable_y_ubicar(equipo, item, novedades=False):
    """
    Limpia el responsable únicamente si sigue coincidiendo con el origen.
    La ubicación se actualiza solo después de confirmar la recepción física.
    """

    if not _responsable_coincide(equipo, item):
        raise RequiereVerificacion(
            "El responsable actual del equipo no coincide "
            "con el responsable original."
        )

    equipo.responsable_nombre = ""
    equipo.responsable_cedula = ""
    equipo.ubicacion = UBICACION_BODEGA

    campos = [
        "responsable_nombre",
        "responsable_cedula",
        "ubicacion",
        "actualizado_en",
    ]

    if novedades:
        equipo.requiere_revision = True
        equipo.motivo_revision = (
            item.observaciones or "Activo recibido con novedades"
        )

        campos.extend([
            "requiere_revision",
            "motivo_revision",
        ])

    equipo.save(update_fields=campos)


def _validar_cedulas_asignacion_equipo(asignacion, cedula_proceso):
    """
    Verifica que las cédulas del receptor y funcionario no se contradigan
    y que la asignación corresponda a la regularización.
    """

    cedula_proceso = _texto(cedula_proceso)
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
        raise RequiereVerificacion(
            "La cédula del receptor y la del funcionario "
            "no coinciden en la asignación original."
        )

    if cedula_proceso not in (
        cedula_receptor,
        cedula_funcionario,
    ):
        raise RequiereVerificacion(
            "La asignación original no corresponde a la "
            "cédula de esta regularización."
        )


def _registrar_resultado_item_transaccional(
    item_id,
    usuario,
    resultado,
    estado_fisico="",
    observaciones="",
):
    """
    Ejecuta la recepción dentro de una transacción.

    Si encuentra una inconsistencia, lanza RequiereVerificacion.
    La transacción completa se revierte antes de guardar la novedad.
    """

    with transaction.atomic():

        item = (
            ItemRegularizacionInventario.objects
            .select_for_update()
            .select_related(
                "regularizacion",
                "equipo",
                "asignacion_equipo",
                "asignacion_equipo__funcionario",
                "asignacion_radio",
            )
            .get(pk=item_id)
        )

        if item.regularizacion.estado in ("COMPLETADA", "CANCELADA"):
            raise RegularizacionError(
                "La regularización ya está cerrada."
            )

        if item.resultado in (
            ItemRegularizacionInventario.Resultado.RECIBIDO,
            ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES,
        ):
            raise RegularizacionError(
                "Este activo ya tiene una recepción registrada."
            )

        item.estado_fisico = estado_fisico
        item.observaciones = observaciones

        # ---------------------------------------------------------
        # RESULTADOS SIN RECEPCIÓN FÍSICA
        # ---------------------------------------------------------

        if resultado == ItemRegularizacionInventario.Resultado.NO_LOCALIZADO:
            item.resultado = resultado

            item.save(update_fields=[
                "resultado",
                "estado_fisico",
                "observaciones",
                "actualizado_en",
            ])

            return item

        if resultado == ItemRegularizacionInventario.Resultado.VERIFICACION:
            item.resultado = resultado

            item.save(update_fields=[
                "resultado",
                "estado_fisico",
                "observaciones",
                "actualizado_en",
            ])

            return item

        # ---------------------------------------------------------
        # VALIDACIONES PARA RECEPCIÓN FÍSICA
        # ---------------------------------------------------------

        _validar_referencias_origen(item)

        novedades = (
            resultado
            == ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES
        )

        equipo = (
            Equipo.objects
            .select_for_update()
            .get(pk=item.equipo_id)
        )

        # ---------------------------------------------------------
        # ORIGEN: ASIGNACIÓN DE EQUIPO
        # ---------------------------------------------------------

        if item.origen == ItemRegularizacionInventario.Origen.EQUIPO:

            asignacion_original = item.asignacion_equipo

            if not asignacion_original:
                raise RequiereVerificacion(
                    "No existe referencia a la asignación original del equipo."
                )

            asignacion = (
                AsignacionEquipo.objects
                .select_for_update()
                .select_related("funcionario")
                .get(pk=asignacion_original.pk)
            )

            if asignacion.equipo_id != item.equipo_id:
                raise RequiereVerificacion(
                    "La asignación original pertenece a otro equipo."
                )

            _validar_cedulas_asignacion_equipo(
                asignacion,
                item.regularizacion.cedula_origen,
            )

            asignacion_actual = (
                AsignacionEquipo.objects
                .select_for_update()
                .filter(
                    equipo_id=equipo.pk,
                    estado=AsignacionEquipo.Estado.ASIGNADO,
                )
                .first()
            )

            if (
                asignacion.estado != AsignacionEquipo.Estado.ASIGNADO
                or not asignacion_actual
                or asignacion_actual.pk != asignacion.pk
            ):
                raise RequiereVerificacion(
                    "La asignación original ya no es la "
                    "asignación activa del equipo."
                )

            if not _responsable_coincide(equipo, item):
                raise RequiereVerificacion(
                    "El responsable actual no coincide "
                    "con el responsable original."
                )

            # Cerrar únicamente la asignación original verificada.
            _cerrar_asignacion_equipo(
                asignacion,
                usuario,
                observaciones,
            )

            _limpiar_responsable_y_ubicar(
                equipo,
                item,
                novedades,
            )

        # ---------------------------------------------------------
        # ORIGEN: ASIGNACIÓN DE RADIO
        # ---------------------------------------------------------

        elif item.origen == ItemRegularizacionInventario.Origen.RADIO:

            asignacion_original = item.asignacion_radio

            if not asignacion_original:
                raise RequiereVerificacion(
                    "No existe referencia a la asignación original del radio."
                )

            asignacion = (
                AsignacionRadio.objects
                .select_for_update()
                .select_related("radio")
                .get(pk=asignacion_original.pk)
            )

            asignacion_actual = (
                AsignacionRadio.objects
                .select_for_update()
                .filter(
                    radio_id=asignacion.radio_id,
                    estado=AsignacionRadio.Estado.ASIGNADO,
                )
                .first()
            )

            radio = (
                Radio.objects
                .select_for_update()
                .get(pk=asignacion.radio_id)
            )

            if radio.equipo_id != item.equipo_id:
                raise RequiereVerificacion(
                    "El radio no está vinculado al equipo "
                    "registrado en esta regularización."
                )

            # Comparar la asignación histórica con la fotografía
            # guardada al crear la regularización.
            asignacion_coincide_con_origen = (
                _texto(asignacion.cedula_funcionario)
                == _texto(item.cedula_radio_origen)
                and _texto(asignacion.cliente_asignado)
                == _texto(item.cliente_origen)
                and _texto(asignacion.puesto_asignado)
                == _texto(item.puesto_origen)
                and _texto(asignacion.coordinador_zona)
                == _texto(item.coordinador_origen)
            )

            # Comparar también el registro actual del radio.
            radio_coincide_con_origen = (
                _texto(radio.cedula_funcionario)
                == _texto(item.cedula_radio_origen)
                and _texto(radio.cliente_asignado)
                == _texto(item.cliente_origen)
                and _texto(radio.puesto_asignado)
                == _texto(item.puesto_origen)
                and _texto(radio.coordinador_zona)
                == _texto(item.coordinador_origen)
            )

            if (
                asignacion.estado != AsignacionRadio.Estado.ASIGNADO
                or not asignacion_actual
                or asignacion_actual.pk != asignacion.pk
                or not asignacion_coincide_con_origen
                or not radio_coincide_con_origen
            ):
                raise RequiereVerificacion(
                    "La asignación histórica o los datos actuales "
                    "del radio no coinciden con el origen."
                )

            if not _responsable_coincide(equipo, item):
                raise RequiereVerificacion(
                    "El responsable del equipo vinculado al radio "
                    "no coincide con el origen."
                )

            # Cerrar primero la asignación original.
            _cerrar_asignacion_radio(
                asignacion,
                usuario,
                observaciones,
            )

            # Limpiar los datos actuales de asignación del radio.
            radio.coordinador_zona = ""
            radio.cedula_funcionario = ""
            radio.cliente_asignado = ""
            radio.puesto_asignado = ""

            if novedades:
                radio.requiere_revision = True
                radio.motivo_revision = (
                    observaciones or "Radio recibido con novedades"
                )

            # Radio.save() sincroniza los datos con Equipo.
            radio.save(update_fields=[
                "coordinador_zona",
                "cedula_funcionario",
                "cliente_asignado",
                "puesto_asignado",
                *(
                    ["requiere_revision", "motivo_revision"]
                    if novedades else []
                ),
            ])

            # Recargar el equipo porque Radio.save() puede sincronizarlo.
            equipo.refresh_from_db()

            # Comprobar que la sincronización no haya cambiado
            # inesperadamente el responsable.
            if not _responsable_coincide(equipo, item):
                raise RequiereVerificacion(
                    "El responsable del equipo vinculado al radio "
                    "cambió durante la recepción."
                )

            equipo.responsable_nombre = ""
            equipo.responsable_cedula = ""
            equipo.ubicacion = UBICACION_BODEGA

            campos_equipo = [
                "responsable_nombre",
                "responsable_cedula",
                "ubicacion",
                "actualizado_en",
            ]

            if novedades:
                equipo.requiere_revision = True
                equipo.motivo_revision = (
                    observaciones or "Radio recibido con novedades"
                )

                campos_equipo.extend([
                    "requiere_revision",
                    "motivo_revision",
                ])

            equipo.save(update_fields=campos_equipo)

        # ---------------------------------------------------------
        # ORIGEN: RESPONSABLE DIRECTO SIN ASIGNACIÓN FORMAL
        # Ejemplo: UPS-01
        # ---------------------------------------------------------

        elif item.origen == ItemRegularizacionInventario.Origen.DIRECTO:

            asignacion_activa_equipo = (
                AsignacionEquipo.objects
                .select_for_update()
                .filter(
                    equipo_id=equipo.pk,
                    estado=AsignacionEquipo.Estado.ASIGNADO,
                )
                .exists()
            )

            asignacion_activa_radio = (
                AsignacionRadio.objects
                .select_for_update()
                .filter(
                    radio__equipo_id=equipo.pk,
                    estado=AsignacionRadio.Estado.ASIGNADO,
                )
                .exists()
            )

            if asignacion_activa_equipo or asignacion_activa_radio:
                raise RequiereVerificacion(
                    "El activo tiene una asignación formal activa "
                    "no contemplada en el origen."
                )

            _limpiar_responsable_y_ubicar(
                equipo,
                item,
                novedades,
            )

        else:
            raise RegularizacionError(
                "El origen del activo no es reconocido."
            )

        # ---------------------------------------------------------
        # CONFIRMAR RECEPCIÓN
        # ---------------------------------------------------------

        item.resultado = resultado
        item.recibido_por = usuario
        item.recibido_en = timezone.now()

        item.save(update_fields=[
            "resultado",
            "estado_fisico",
            "observaciones",
            "recibido_por",
            "recibido_en",
            "actualizado_en",
        ])

        return item


def registrar_resultado_item(
    item_id,
    usuario,
    resultado,
    estado_fisico="",
    observaciones="",
):
    """
    Punto de entrada del servicio.

    Si ocurre una inconsistencia:
    1. Se revierte la transacción de recepción.
    2. Se registra VERIFICACION en una transacción independiente.
    3. No se deja cerrada una asignación por una recepción fallida.
    """

    if not usuario or not usuario.is_authenticated:
        raise RegularizacionError(
            "Se requiere un usuario autenticado."
        )

    resultados_validos = {
        ItemRegularizacionInventario.Resultado.RECIBIDO,
        ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES,
        ItemRegularizacionInventario.Resultado.NO_LOCALIZADO,
        ItemRegularizacionInventario.Resultado.VERIFICACION,
    }

    if resultado not in resultados_validos:
        raise RegularizacionError(
            "El resultado indicado no está permitido."
        )

    try:
        return _registrar_resultado_item_transaccional(
            item_id=item_id,
            usuario=usuario,
            resultado=resultado,
            estado_fisico=estado_fisico,
            observaciones=observaciones,
        )

    except RequiereVerificacion as exc:

        # Esta transacción comienza después de que la transacción
        # de recepción fallida ya fue revertida.
        with transaction.atomic():

            item = (
                ItemRegularizacionInventario.objects
                .select_for_update()
                .select_related("regularizacion")
                .get(pk=item_id)
            )

            if item.regularizacion.estado in ("COMPLETADA", "CANCELADA"):
                raise RegularizacionError(
                    "La regularización ya está cerrada."
                )

            if item.resultado in (
                ItemRegularizacionInventario.Resultado.RECIBIDO,
                ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES,
            ):
                raise RegularizacionError(
                    "El activo ya tiene una recepción registrada."
                )

            item.estado_fisico = estado_fisico
            item.observaciones = observaciones

            _guardar_verificacion(
                item,
                str(exc),
            )

            return item
