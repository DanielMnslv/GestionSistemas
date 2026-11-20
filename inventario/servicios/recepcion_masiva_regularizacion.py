
from django.db import transaction
from django.utils import timezone

from inventario.models import (
    RegularizacionInventario,
    ItemRegularizacionInventario,
)

from .regularizacion import (
    RegularizacionError,
    RequiereVerificacion,
    _registrar_resultado_item_transaccional,
)


RESULTADOS_PERMITIDOS = {
    ItemRegularizacionInventario.Resultado.RECIBIDO,
    ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES,
}


def recibir_regularizacion_masiva(
    regularizacion_id,
    usuario,
    inspecciones,
):
    """
    Recibe todos los activos de una regularización en una sola transacción.

    inspecciones debe tener esta estructura:
    {
        item_id: {
            "resultado": "RECIBIDO" o "RECIBIDO_NOVEDADES",
            "estado_fisico": "...",
            "observaciones": "...",
        }
    }

    Si falla un solo activo, se revierte toda la recepción.
    """

    if not usuario or not usuario.is_authenticated:
        raise RegularizacionError(
            "Debes iniciar sesión para confirmar la recepción."
        )

    if not isinstance(inspecciones, dict):
        raise RegularizacionError(
            "Los datos de inspección no tienen un formato válido."
        )

    with transaction.atomic():

        regularizacion = (
            RegularizacionInventario.objects
            .select_for_update()
            .get(pk=regularizacion_id)
        )

        if regularizacion.estado in (
            RegularizacionInventario.Estado.COMPLETADA,
            RegularizacionInventario.Estado.CANCELADA,
        ):
            raise RegularizacionError(
                "La regularización está cerrada y no admite recepciones."
            )

        items = list(
            ItemRegularizacionInventario.objects
            .select_for_update()
            .filter(regularizacion=regularizacion)
            .order_by("id")
        )

        if not items:
            raise RegularizacionError(
                "La regularización no contiene activos."
            )

        ids_items = {item.pk for item in items}

        try:
            ids_recibidos = {int(pk) for pk in inspecciones.keys()}
        except (TypeError, ValueError):
            raise RegularizacionError(
                "Hay identificadores de activos inválidos."
            )

        if ids_recibidos != ids_items:
            raise RegularizacionError(
                "La inspección debe incluir exactamente todos los activos "
                "de esta regularización. No se recibió ningún activo."
            )

        # Validación completa antes de comenzar a cerrar asignaciones.
        datos_validados = {}

        for item in items:
            datos = inspecciones[item.pk]
            resultado = str(datos.get("resultado", "")).strip()
            estado_fisico = str(
                datos.get("estado_fisico", "")
            ).strip()
            observaciones = str(
                datos.get("observaciones", "")
            ).strip()

            if resultado not in RESULTADOS_PERMITIDOS:
                raise RegularizacionError(
                    f"{item.equipo.placa}: selecciona un resultado "
                    "de recepción válido."
                )

            if not estado_fisico:
                raise RegularizacionError(
                    f"{item.equipo.placa}: falta registrar el estado físico."
                )

            if len(estado_fisico) > 100:
                raise RegularizacionError(
                    f"{item.equipo.placa}: el estado físico supera "
                    "los 100 caracteres permitidos."
                )

            if (
                resultado
                == ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES
                and not observaciones
            ):
                raise RegularizacionError(
                    f"{item.equipo.placa}: describe las novedades "
                    "antes de confirmar."
                )

            if item.resultado in (
                ItemRegularizacionInventario.Resultado.RECIBIDO,
                ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES,
            ):
                raise RegularizacionError(
                    f"{item.equipo.placa}: ya tiene una recepción registrada."
                )

            datos_validados[item.pk] = {
                "resultado": resultado,
                "estado_fisico": estado_fisico,
                "observaciones": observaciones,
            }

        # Una única transacción para todos los activos.
        # La función individual utiliza transaction.atomic() anidado:
        # sus cambios quedan subordinados a esta transacción exterior.
        for item in items:
            datos = datos_validados[item.pk]

            try:
                _registrar_resultado_item_transaccional(
                    item_id=item.pk,
                    usuario=usuario,
                    resultado=datos["resultado"],
                    estado_fisico=datos["estado_fisico"],
                    observaciones=datos["observaciones"],
                )
            except RequiereVerificacion as exc:
                raise RegularizacionError(
                    f"No se pudo recibir el lote. "
                    f"Activo {item.equipo.placa}: {exc} "
                    "No se confirmó ningún activo."
                ) from exc

        # Comprobación final antes de cerrar el proceso.
        pendientes = (
            ItemRegularizacionInventario.objects
            .filter(regularizacion=regularizacion)
            .exclude(resultado__in=RESULTADOS_PERMITIDOS)
            .count()
        )

        if pendientes:
            raise RegularizacionError(
                "La recepción no puede finalizar: todavía existen "
                "activos sin recibir."
            )

        regularizacion.estado = (
            RegularizacionInventario.Estado.COMPLETADA
        )
        regularizacion.cerrado_por = usuario
        regularizacion.cerrado_en = timezone.now()
        regularizacion.save(
            update_fields=[
                "estado",
                "cerrado_por",
                "cerrado_en",
                "actualizado_en",
            ]
        )

        return {
            "regularizacion": regularizacion,
            "total": len(items),
            "con_novedades": sum(
                1
                for datos in datos_validados.values()
                if datos["resultado"]
                == ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES
            ),
        }
