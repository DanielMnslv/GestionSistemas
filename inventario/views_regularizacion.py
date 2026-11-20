
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    RegularizacionInventario,
    ItemRegularizacionInventario,
)
from .views import requiere_permiso
from .servicios.carga_regularizacion import (
    crear_regularizacion_inventario,
    ErrorCargaRegularizacion,
)
from .servicios.regularizacion import (
    registrar_resultado_item,
    RegularizacionError,
    RequiereVerificacion,
)
from .servicios.recepcion_masiva_regularizacion import (
    recibir_regularizacion_masiva,
)


@login_required
@requiere_permiso("regularizacion_inventario")
def regularizaciones_lista(request):
    """Listado de procesos de regularización de inventario."""

    consulta = (
        RegularizacionInventario.objects
        .select_related("creado_por")
        .annotate(
            total_items=Count("items", distinct=True),
            pendientes=Count(
                "items",
                filter=Q(
                    items__resultado=(
                        ItemRegularizacionInventario.Resultado.PENDIENTE
                    )
                ),
                distinct=True,
            ),
            recibidos=Count(
                "items",
                filter=Q(
                    items__resultado__in=[
                        ItemRegularizacionInventario.Resultado.RECIBIDO,
                        ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES,
                    ]
                ),
                distinct=True,
            ),
            novedades=Count(
                "items",
                filter=Q(
                    items__resultado=(
                        ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES
                    )
                ),
                distinct=True,
            ),
            no_localizados=Count(
                "items",
                filter=Q(
                    items__resultado=(
                        ItemRegularizacionInventario.Resultado.NO_LOCALIZADO
                    )
                ),
                distinct=True,
            ),
            en_verificacion=Count(
                "items",
                filter=Q(
                    items__resultado=(
                        ItemRegularizacionInventario.Resultado.VERIFICACION
                    )
                ),
                distinct=True,
            ),
        )
        .order_by("-creado_en", "-id")
    )

    estado = request.GET.get("estado", "").strip()
    cedula = request.GET.get("cedula", "").strip()

    if estado in RegularizacionInventario.Estado.values:
        consulta = consulta.filter(estado=estado)

    if cedula:
        consulta = consulta.filter(cedula_origen__icontains=cedula)

    # Paginación conservando los filtros de búsqueda.
    parametros = request.GET.copy()
    parametros.pop("page", None)

    paginator = Paginator(consulta, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "inventario/regularizaciones_lista.html",
        {
            "page_obj": page_obj,
            "regularizaciones": page_obj.object_list,
            "estado_filtro": estado,
            "cedula_filtro": cedula,
            "estados": RegularizacionInventario.Estado.choices,
            "parametros": parametros.urlencode(),
        },
    )


@login_required
@requiere_permiso("regularizacion_inventario")
def regularizacion_crear(request):
    """Formulario para crear un proceso independiente de regularización."""

    if request.method == "POST":
        cedula = request.POST.get("cedula_origen", "").strip()
        nombre = request.POST.get("nombre_origen", "").strip()
        observaciones = request.POST.get("observaciones", "").strip()

        if not cedula:
            messages.error(
                request,
                "Debes ingresar la cédula de origen.",
            )
            return render(
                request,
                "inventario/regularizacion_crear.html",
                {
                    "cedula_origen": cedula,
                    "nombre_origen": nombre,
                    "observaciones": observaciones,
                },
            )

        try:
            regularizacion = crear_regularizacion_inventario(
                cedula=cedula,
                usuario=request.user,
                nombre_origen=nombre,
                observaciones=observaciones,
            )

        except ErrorCargaRegularizacion as exc:
            messages.error(request, str(exc))
            return render(
                request,
                "inventario/regularizacion_crear.html",
                {
                    "cedula_origen": cedula,
                    "nombre_origen": nombre,
                    "observaciones": observaciones,
                },
            )

        messages.success(
            request,
            (
                "Regularización creada correctamente. "
                f"Se incluyeron {regularizacion.items.count()} activos. "
                "No se han modificado las asignaciones originales."
            ),
        )

        return redirect(
            "inventario:regularizacion_detalle",
            pk=regularizacion.pk,
        )

    return render(
        request,
        "inventario/regularizacion_crear.html",
        {},
    )


@login_required
@requiere_permiso("regularizacion_inventario")
def regularizacion_detalle(request, pk):
    """Detalle de un proceso y sus activos incluidos."""

    regularizacion = get_object_or_404(
        RegularizacionInventario.objects.select_related(
            "creado_por",
            "cerrado_por",
        ),
        pk=pk,
    )

    items = (
        ItemRegularizacionInventario.objects
        .filter(regularizacion=regularizacion)
        .select_related(
            "equipo",
            "asignacion_equipo",
            "asignacion_radio",
            "recibido_por",
        )
        .order_by("origen", "equipo__placa", "id")
    )

    resumen = {
        "total": items.count(),
        "pendientes": items.filter(
            resultado=ItemRegularizacionInventario.Resultado.PENDIENTE
        ).count(),
        "recibidos": items.filter(
            resultado__in=[
                ItemRegularizacionInventario.Resultado.RECIBIDO,
                ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES,
            ]
        ).count(),
        "novedades": items.filter(
            resultado=(
                ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES
            )
        ).count(),
        "no_localizados": items.filter(
            resultado=ItemRegularizacionInventario.Resultado.NO_LOCALIZADO
        ).count(),
        "verificacion": items.filter(
            resultado=ItemRegularizacionInventario.Resultado.VERIFICACION
        ).count(),
    }

    # Paginación conservando los parámetros de consulta.
    parametros = request.GET.copy()
    parametros.pop("page", None)

    paginator = Paginator(items, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "inventario/regularizacion_detalle.html",
        {
            "regularizacion": regularizacion,
            "items": page_obj.object_list,
            "page_obj": page_obj,
            "resumen": resumen,
            "resultados": ItemRegularizacionInventario.Resultado.choices,
            "proceso_cerrado": regularizacion.estado in [
                RegularizacionInventario.Estado.COMPLETADA,
                RegularizacionInventario.Estado.CANCELADA,
            ],
            "parametros": parametros.urlencode(),
        },
    )


@login_required
@requiere_permiso("regularizacion_inventario")
@require_POST
def regularizacion_item_recibir(request, item_id):
    """Registra el resultado de verificación de un activo individual."""

    item = get_object_or_404(
        ItemRegularizacionInventario.objects.select_related(
            "regularizacion"
        ),
        pk=item_id,
    )

    regularizacion = item.regularizacion

    if regularizacion.estado in [
        RegularizacionInventario.Estado.COMPLETADA,
        RegularizacionInventario.Estado.CANCELADA,
    ]:
        messages.error(
            request,
            "No se pueden modificar elementos de una regularización cerrada.",
        )
        return redirect(
            "inventario:regularizacion_detalle",
            pk=regularizacion.pk,
        )

    resultado = request.POST.get("resultado", "").strip()
    estado_fisico = request.POST.get("estado_fisico", "").strip()
    observaciones = request.POST.get("observaciones", "").strip()

    resultados_con_recepcion = {
        ItemRegularizacionInventario.Resultado.RECIBIDO,
        ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES,
    }

    if resultado in resultados_con_recepcion:
        if request.POST.get("confirmar_recepcion") != "si":
            messages.error(
                request,
                "Debes confirmar que el activo fue recibido físicamente.",
            )
            return redirect(
                "inventario:regularizacion_detalle",
                pk=regularizacion.pk,
            )

    elif resultado == ItemRegularizacionInventario.Resultado.NO_LOCALIZADO:
        if not observaciones:
            messages.error(
                request,
                "Debes explicar por qué el activo no fue localizado.",
            )
            return redirect(
                "inventario:regularizacion_detalle",
                pk=regularizacion.pk,
            )

    try:
        item_actualizado = registrar_resultado_item(
            item_id=item.pk,
            usuario=request.user,
            resultado=resultado,
            estado_fisico=estado_fisico,
            observaciones=observaciones,
        )

        # El proceso pasa a recuperación cuando comienza su gestión.
        # No se completa automáticamente.
        if regularizacion.estado == RegularizacionInventario.Estado.BORRADOR:
            regularizacion.estado = (
                RegularizacionInventario.Estado.EN_RECUPERACION
            )
            regularizacion.actualizado_en = timezone.now()
            regularizacion.save(
                update_fields=["estado", "actualizado_en"]
            )

        if item_actualizado.resultado == (
            ItemRegularizacionInventario.Resultado.VERIFICACION
        ):
            messages.warning(
                request,
                (
                    "El activo quedó en verificación. "
                    "No se cerró su asignación."
                ),
            )
        else:
            messages.success(
                request,
                "Se registró el resultado del activo correctamente.",
            )

    except RegularizacionError as exc:
        messages.error(request, str(exc))

    return redirect(
        "inventario:regularizacion_detalle",
        pk=regularizacion.pk,
    )


@login_required
@requiere_permiso("regularizacion_inventario")
def regularizacion_recepcion_masiva(request, pk):
    """Inspección y confirmación masiva de todos los activos."""

    regularizacion = get_object_or_404(
        RegularizacionInventario,
        pk=pk,
    )

    if regularizacion.estado in (
        RegularizacionInventario.Estado.COMPLETADA,
        RegularizacionInventario.Estado.CANCELADA,
    ):
        messages.error(
            request,
            "Esta regularización está cerrada.",
        )
        return redirect(
            "inventario:regularizacion_detalle",
            pk=pk,
        )

    items = list(
        ItemRegularizacionInventario.objects
        .filter(regularizacion=regularizacion)
        .select_related("equipo")
        .order_by("equipo__tipo", "equipo__placa", "id")
    )

    if request.method == "POST":

        if request.POST.get("confirmar_lote") != "si":
            messages.error(
                request,
                "Debes confirmar expresamente la recepción del lote.",
            )
        else:
            inspecciones = {}

            for item in items:
                inspecciones[item.pk] = {
                    "resultado": request.POST.get(
                        f"resultado_{item.pk}", ""
                    ),
                    "estado_fisico": request.POST.get(
                        f"estado_fisico_{item.pk}", ""
                    ),
                    "observaciones": request.POST.get(
                        f"observaciones_{item.pk}", ""
                    ),
                }

            try:
                resultado = recibir_regularizacion_masiva(
                    regularizacion_id=regularizacion.pk,
                    usuario=request.user,
                    inspecciones=inspecciones,
                )

                messages.success(
                    request,
                    (
                        f"Recepción masiva completada. "
                        f"Se recibieron {resultado['total']} activos. "
                        f"Con novedades: {resultado['con_novedades']}. "
                        "La regularización quedó cerrada."
                    ),
                )

                return redirect(
                    "inventario:regularizacion_detalle",
                    pk=pk,
                )

            except (RegularizacionError, RequiereVerificacion) as exc:
                messages.error(request, str(exc))

        # Conservar lo escrito si la validación no permite confirmar.
        for item in items:
            item.form_resultado = request.POST.get(
                f"resultado_{item.pk}", ""
            )
            item.form_estado_fisico = request.POST.get(
                f"estado_fisico_{item.pk}", ""
            )
            item.form_observaciones = request.POST.get(
                f"observaciones_{item.pk}", ""
            )

    return render(
        request,
        "inventario/regularizacion_recepcion_masiva.html",
        {
            "regularizacion": regularizacion,
            "items": items,
            "total_items": len(items),
            "resultados_recepcion": [
                (
                    ItemRegularizacionInventario.Resultado.RECIBIDO,
                    "Recibido",
                ),
                (
                    ItemRegularizacionInventario.Resultado.RECIBIDO_NOVEDADES,
                    "Recibido con novedades",
                ),
            ],
        },
    )
