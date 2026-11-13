
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db import transaction, IntegrityError
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from urllib.parse import urlencode
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.core.paginator import Paginator

from .forms import (
    MantenimientoEquipoForm,
    MantenimientoProgramadoForm,
    AsignacionRadioForm,
    CLAUSULA_CONFIDENCIALIDAD,
    RadioBajaForm,
    RadioForm,
)
from .orden import orden_placa
from .permisos import puede, requiere_permiso
from .radio_componentes import (
    COMPONENTES_TRANSFERIBLES_RADIO,
    componentes_faltantes_radio,
)
from .models import (
    Cliente,
    Equipo,
    Radio,
    MantenimientoEquipo,
    MantenimientoProgramado,
    AsignacionRadio,
    TransferenciaComponentesRadio,
)

def _fecha_iso_valida(valor):
    try:
        return date.fromisoformat(valor).isoformat() == valor
    except (ValueError, TypeError):
        return False


def equipo_de_la_url(request):
    """Id del equipo indicado con ?equipo=<placa>, para preseleccionarlo."""
    placa = request.GET.get("equipo", "").strip()
    if not placa:
        return None
    return Equipo.objects.filter(placa=placa).values_list("pk", flat=True).first()


def pide_modal(request):
    """True si el formulario se pidió desde la ventana emergente del panel."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def abrir_en_ventana(request, variante):
    """Registrar y Programar ya no tienen página propia: viven en la ventana emergente.

    Quien llega por un enlace directo (ficha del equipo, marcador antiguo) va al panel
    de mantenimiento y la ventana se abre sola, con el equipo preseleccionado.
    """
    parametros = {"abrir": variante}
    placa = request.GET.get("equipo", "").strip()
    if placa:
        parametros["equipo"] = placa
    return redirect(
        f"{reverse('inventario:panel_mantenimientos')}?{urlencode(parametros)}"
    )


def abrir_completar_en_ventana(programacion_id):
    """"Completar" tampoco tiene página propia: va a la lista de programados y la ventana se abre sola."""
    parametros = urlencode({"abrir": "completar", "programacion": programacion_id})
    return redirect(
        f"{reverse('inventario:mantenimientos_programados_lista')}?{parametros}"
    )


def equipo_fijo_de(request):
    """Equipo con el que se abrió la ventana emergente (viene desde su fila)."""
    if request.method == "POST":
        if request.POST.get("equipo_fijo") != "1":
            return None
        pk = request.POST.get("equipo", "")
        return Equipo.objects.filter(pk=pk).first() if pk.isdigit() else None
    pk = equipo_de_la_url(request)
    return Equipo.objects.filter(pk=pk).first() if pk else None


def contexto_modal(formulario, equipo_fijo, titulo, accion, variante):
    """Contexto común de las ventanas emergentes de Registrar y Programar."""
    contexto = {
        "formulario": formulario,
        "titulo": titulo,
        "accion": accion,
        "variante": variante,
    }
    if equipo_fijo:
        contexto["equipo_fijo"] = equipo_fijo
        contexto["equipo_etiqueta"] = (
            formulario.fields["equipo"].label_from_instance(equipo_fijo)
        )
    return contexto


def paginar(request, consulta, por_pagina):
    """Página pedida y la consulta actual sin "page" (para los enlaces)."""
    page_obj = Paginator(consulta, por_pagina).get_page(
        request.GET.get("page")
    )
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return page_obj, parametros.urlencode()


def filas_por_pagina(request, defecto):
    """Filas por página: la página de escritorio la ajusta a la altura de la
    pantalla con el parámetro "pp" (ver _mant_ajuste_filas.html)."""
    try:
        return max(3, min(100, int(request.GET.get("pp", defecto))))
    except ValueError:
        return defecto


def _volver_a_equipos(radio_id):
    radio = get_object_or_404(
        Radio.objects.select_related("equipo"), pk=radio_id
    )
    placa = radio.equipo.placa if radio.equipo_id else radio.placa
    consulta = urlencode({"q": placa, "estado": ""})
    return redirect(reverse("inventario:equipos_lista") + "?" + consulta)


def _volver_a_pestana_radio(radio_id, pestana):
    radio = get_object_or_404(
        Radio.objects.select_related("equipo"), pk=radio_id
    )
    destino = reverse(
        "inventario:equipo_pestanas", args=[radio.equipo.placa]
    )
    return redirect(
        f"{destino}?embed=1&pestanas_radio=1#{pestana}"
    )


def _render_radio_editar_con_errores(request, radio, formulario):
    return render(request, "inventario/radio_pestanas.html", {
        "radio": radio,
        "asignaciones": [],
        "asignacion_activa": None,
        "mantenimientos": [],
        "formulario": formulario,
        "formulario_baja": RadioBajaForm(),
        "clausula": CLAUSULA_CONFIDENCIALIDAD,
        "pestana_inicial": "editar",
    })


@login_required
@xframe_options_sameorigin
def radio_detalle(request, radio_id):
    return _volver_a_equipos(radio_id)


@login_required
@requiere_permiso("radios")
def radio_crear(request):
    formulario = RadioForm(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        radio = formulario.save()
        messages.success(request, f"El radio {radio} quedó registrado.")
        return _volver_a_equipos(radio.pk)

    return render(
        request,
        "inventario/radio_form.html",
        {"formulario": formulario, "titulo": "Registrar radio"},
    )


@login_required
@xframe_options_sameorigin
@requiere_permiso("radios")
def radio_editar(request, radio_id):
    radio = get_object_or_404(Radio, pk=radio_id)
    if request.method != "POST":
        return _volver_a_equipos(radio.pk)

    formulario = RadioForm(request.POST, instance=radio)
    if formulario.is_valid():
        formulario.save()
        messages.success(request, "Los datos del radio se actualizaron.")
        if request.POST.get("pestanas_radio") == "1":
            return _volver_a_pestana_radio(radio.pk, "editar")
        return _volver_a_equipos(radio.pk)

    if request.POST.get("pestanas_radio") == "1":
        return _render_radio_editar_con_errores(request, radio, formulario)
    messages.error(
        request,
        "No se pudieron guardar los cambios del radio. "
        + formulario.errors.as_text().replace("\n", " "),
    )
    return _volver_a_equipos(radio.pk)


@login_required
@xframe_options_sameorigin
@requiere_permiso("radios")
def radio_transferir_componentes(request, radio_id):
    if request.method != "POST":
        return _volver_a_equipos(radio_id)

    destino_pk = request.POST.get("radio_destino", "")
    if not destino_pk.isdigit() or int(destino_pk) == radio_id:
        messages.error(request, "Selecciona otro radio activo como destino.")
        return _volver_a_equipos(radio_id)

    with transaction.atomic():
        radios = {
            radio.pk: radio
            for radio in Radio.objects.select_for_update()
            .filter(pk__in=(radio_id, int(destino_pk)))
            .order_by("pk")
        }
        origen = radios.get(radio_id)
        destino = radios.get(int(destino_pk))
        if origen is None:
            get_object_or_404(Radio, pk=radio_id)
        if not origen.activo or destino is None or not destino.activo:
            messages.error(
                request,
                "Solo se pueden transferir componentes entre radios activos.",
            )
            return _volver_a_equipos(radio_id)

        a_transferir = componentes_faltantes_radio(origen, destino)
        if not a_transferir:
            messages.error(
                request,
                "El radio destino ya tiene todos los componentes disponibles "
                "en el radio de origen.",
            )
            return _volver_a_equipos(radio_id)

        campos_origen = set()
        campos_destino = set()
        registro_componentes = []
        for componente in a_transferir:
            clave = componente["clave"]
            if clave == "baterias":
                cantidad_origen = sum(
                    getattr(origen, campo) is True
                    for campo in ("bateria_1", "bateria_2")
                )
                baterias_origen = [
                    campo for campo in ("bateria_1", "bateria_2")
                    if getattr(origen, campo) is True
                ][:componente["cantidad"]]
                baterias_destino = [
                    campo for campo in ("bateria_1", "bateria_2")
                    if getattr(destino, campo) is not True
                ][:componente["cantidad"]]
                for campo_origen, campo_destino in zip(
                    baterias_origen, baterias_destino
                ):
                    setattr(origen, campo_origen, False)
                    setattr(destino, campo_destino, True)
                    campos_origen.add(campo_origen)
                    campos_destino.add(campo_destino)
                campos_origen.add("estado_baterias")
                campos_destino.add("estado_baterias")
                if cantidad_origen == len(baterias_origen):
                    origen.estado_baterias = ""
            else:
                _, _, campo, campo_estado = next(
                    dato for dato in COMPONENTES_TRANSFERIBLES_RADIO
                    if dato[0] == clave
                )
                setattr(origen, campo, False)
                setattr(destino, campo, True)
                campos_origen.update((campo, campo_estado))
                campos_destino.update((campo, campo_estado))

            estado = componente["estado"]
            campo_estado = next(
                dato[3] for dato in COMPONENTES_TRANSFERIBLES_RADIO
                if dato[0] == clave
            )
            if clave != "baterias":
                setattr(origen, campo_estado, "")
            setattr(destino, campo_estado, estado)
            registro_componentes.append({
                "nombre": componente["nombre"],
                "cantidad": componente["cantidad"],
                "estado": estado,
            })

        origen.save(update_fields=sorted(campos_origen | {"actualizado_en"}))
        destino.save(update_fields=sorted(campos_destino | {"actualizado_en"}))
        TransferenciaComponentesRadio.objects.create(
            radio_origen=origen,
            radio_destino=destino,
            etiqueta_origen=origen.etiqueta,
            etiqueta_destino=destino.etiqueta,
            componentes=registro_componentes,
            registrado_por=request.user,
        )

    nombres = ", ".join(item["nombre"] for item in registro_componentes)
    messages.success(
        request,
        f"Componentes transferidos a {destino.etiqueta}: {nombres}.",
    )
    return _volver_a_equipos(radio_id)


@login_required
@xframe_options_sameorigin
@requiere_permiso("radios")
def radio_dar_baja(request, radio_id):
    radio = get_object_or_404(Radio, pk=radio_id)
    formulario = RadioBajaForm(request.POST or None)
    if request.method != "POST":
        return _volver_a_equipos(radio.pk)

    if not radio.activo:
        messages.error(request, "El radio ya está dado de baja.")
    elif radio.asignaciones.filter(
        estado=AsignacionRadio.Estado.ASIGNADO
    ).exists():
        messages.error(
            request,
            "El radio tiene una entrega activa. Registra primero su "
            "devolución.",
        )
    elif not formulario.is_valid():
        messages.error(request, "Indica el motivo de la baja.")
    else:
        radio.activo = False
        radio.estado_radio = Radio.ESTADO_BAJA
        radio.fecha_baja = timezone.localdate()
        radio.motivo_baja = formulario.cleaned_data["motivo_baja"]
        radio.save(update_fields=[
            "activo", "estado_radio", "fecha_baja", "motivo_baja",
            "actualizado_en",
        ])
        messages.success(request, "El radio quedó dado de baja.")

    if request.POST.get("pestanas_radio") == "1":
        return _volver_a_pestana_radio(radio.pk, "baja")
    return _volver_a_equipos(radio.pk)


@login_required
@xframe_options_sameorigin
@requiere_permiso("radios")
def radio_reactivar(request, radio_id):
    radio = get_object_or_404(Radio, pk=radio_id)
    if request.method != "POST":
        return _volver_a_equipos(radio.pk)

    if not radio.activo:
        radio.activo = True
        radio.estado_radio = ""  # hay que volver a indicar su estado
        radio.fecha_baja = None
        radio.motivo_baja = ""
        radio.save(update_fields=[
            "activo", "estado_radio", "fecha_baja", "motivo_baja",
            "actualizado_en",
        ])
        messages.success(request, "El radio volvió al inventario activo.")

    if request.POST.get("pestanas_radio") == "1":
        return _volver_a_pestana_radio(radio.pk, "baja")
    return _volver_a_equipos(radio.pk)


@login_required
def mantenimientos_lista(request):
    mantenimientos = MantenimientoEquipo.objects.select_related(
        "equipo", "equipo__radio", "registrado_por"
    ).all()

    # Filtros recibidos desde la URL.
    busqueda = request.GET.get("q", "").strip()
    tipo = request.GET.get("tipo", "").strip()
    resultado = request.GET.get("resultado", "").strip()
    estado_final = request.GET.get("estado_final", "").strip()
    fecha_desde = request.GET.get("fecha_desde", "").strip()
    fecha_hasta = request.GET.get("fecha_hasta", "").strip()
    origen = request.GET.get("origen", "").strip()
    tipo_equipo = request.GET.get("tipo_equipo", "").strip()
    tecnico = request.GET.get("tecnico", "").strip()

    if tipo_equipo in Equipo.Tipo.values:
        mantenimientos = mantenimientos.filter(equipo__tipo=tipo_equipo)
    else:
        tipo_equipo = ""

    # Búsqueda general.
    if busqueda:
        mantenimientos = mantenimientos.filter(
            Q(equipo__placa__icontains=busqueda)
            | Q(equipo__serial__icontains=busqueda)
            | Q(equipo__radio__codigo_fisico__icontains=busqueda)
            | Q(tecnico_responsable__icontains=busqueda)
            | Q(trabajo_realizado__icontains=busqueda)
        )
    if tecnico:
        mantenimientos = mantenimientos.filter(
            tecnico_responsable__icontains=tecnico
        )

    # Tipo de intervención.
    tipos_validos = dict(MantenimientoEquipo.Tipo.choices)
    if tipo in tipos_validos:
        mantenimientos = mantenimientos.filter(tipo=tipo)
    else:
        tipo = ""

    # Resultado de la intervención.
    resultados_validos = dict(MantenimientoEquipo.Resultado.choices)
    if resultado in resultados_validos:
        mantenimientos = mantenimientos.filter(resultado=resultado)
    else:
        resultado = ""

    # Estado final del radio.
    estados_validos = dict(MantenimientoEquipo.EstadoFinal.choices)
    if estado_final in estados_validos:
        mantenimientos = mantenimientos.filter(
            estado_final=estado_final
        )
    else:
        estado_final = ""

    # Rango de fechas. Solo se aceptan fechas ISO válidas.
    if fecha_desde and _fecha_iso_valida(fecha_desde):
        mantenimientos = mantenimientos.filter(
            fecha_intervencion__date__gte=fecha_desde
        )
    else:
        fecha_desde = ""

    if fecha_hasta and _fecha_iso_valida(fecha_hasta):
        mantenimientos = mantenimientos.filter(
            fecha_intervencion__date__lte=fecha_hasta
        )
    else:
        fecha_hasta = ""

    # Diferenciar registros importados de registros nuevos.
    if origen == "historico":
        mantenimientos = mantenimientos.exclude(origen_archivo="")
    elif origen == "nuevo":
        mantenimientos = mantenimientos.filter(origen_archivo="")
    else:
        origen = ""

    # Orden cronológico descendente.
    mantenimientos = mantenimientos.order_by(
        "-fecha_intervencion", "-id"
    )

    page_obj, parametros = paginar(
        request, mantenimientos, filas_por_pagina(request, 50)
    )

    contexto = {
        "mantenimientos": page_obj.object_list,
        "page_obj": page_obj,
        "parametros": parametros,
        "busqueda": busqueda,
        "tecnico_seleccionado": tecnico,
        "tipo_seleccionado": tipo,
        "resultado_seleccionado": resultado,
        "estado_final_seleccionado": estado_final,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "origen_seleccionado": origen,
        "tipo_equipo_seleccionado": tipo_equipo,
        "tipos_equipo": Equipo.Tipo.choices,
        "tipos_mantenimiento": MantenimientoEquipo.Tipo.choices,
        "resultados_mantenimiento": MantenimientoEquipo.Resultado.choices,
        "estados_finales": MantenimientoEquipo.EstadoFinal.choices,
        "total_resultados": page_obj.paginator.count,
        "total_registros": MantenimientoEquipo.objects.count(),
        "pestana": "historial",
        "total_equipos": Equipo.objects.filter(activo=True).count(),
        "hay_filtros": any([
            busqueda, tecnico, tipo, resultado, estado_final, fecha_desde,
            fecha_hasta, origen, tipo_equipo,
        ]),
        "hay_filtros_extra": any([
            tecnico, estado_final, fecha_desde, fecha_hasta, origen,
        ]),
    }

    return render(
        request,
        "inventario/mantenimientos_lista.html",
        contexto,
    )


@login_required
@requiere_permiso("mantenimientos")
def mantenimiento_crear(request):
    if not pide_modal(request):
        return abrir_en_ventana(request, "registrar")

    equipo_fijo = equipo_fijo_de(request)

    if request.method == "POST":
        formulario = MantenimientoEquipoForm(request.POST)

        if formulario.is_valid():
            with transaction.atomic():
                mantenimiento = formulario.save(commit=False)
                mantenimiento.registrado_por = request.user
                mantenimiento.save()

            messages.success(request, "La intervención quedó registrada.")

            # El panel recarga la lista y muestra el mensaje.
            return JsonResponse({"ok": True})
    else:
        formulario = MantenimientoEquipoForm(
            initial={
                "fecha_intervencion": timezone.localtime().strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "equipo": equipo_de_la_url(request),
                # Quien registra suele ser quien hizo el trabajo.
                "tecnico_responsable": (
                    request.user.get_full_name() or request.user.get_username()
                ),
            }
        )

    contexto = contexto_modal(
        formulario, equipo_fijo, "Registrar intervención",
        reverse("inventario:mantenimiento_crear"), "registrar",
    )

    return render(request, "inventario/_mantenimiento_modal.html", contexto)


@login_required
def mantenimientos_programados_lista(request):
    programaciones = (
        MantenimientoProgramado.objects.select_related(
            "equipo", "equipo__radio", "creado_por"
        ).all()
    )

    estado = request.GET.get("estado", "PROGRAMADO")
    busqueda = request.GET.get("q", "").strip()
    tipo_equipo = request.GET.get("tipo_equipo", "").strip()
    tipo = request.GET.get("tipo", "").strip()
    fecha_desde = request.GET.get("fecha_desde", "").strip()
    fecha_hasta = request.GET.get("fecha_hasta", "").strip()

    if estado in ("PROGRAMADO", "COMPLETADO", "CANCELADO"):
        programaciones = programaciones.filter(estado=estado)
    else:
        estado = ""
    if busqueda:
        programaciones = programaciones.filter(
            Q(equipo__placa__icontains=busqueda)
            | Q(equipo__serial__icontains=busqueda)
            | Q(equipo__radio__codigo_fisico__icontains=busqueda)
            | Q(descripcion__icontains=busqueda)
            | Q(observaciones__icontains=busqueda)
        )
    if tipo_equipo in Equipo.Tipo.values:
        programaciones = programaciones.filter(equipo__tipo=tipo_equipo)
    else:
        tipo_equipo = ""
    tipos_mantenimiento = dict(MantenimientoEquipo.Tipo.choices)
    if tipo in tipos_mantenimiento:
        programaciones = programaciones.filter(tipo=tipo)
    else:
        tipo = ""
    if fecha_desde and _fecha_iso_valida(fecha_desde):
        programaciones = programaciones.filter(fecha_programada__gte=fecha_desde)
    else:
        fecha_desde = ""
    if fecha_hasta and _fecha_iso_valida(fecha_hasta):
        programaciones = programaciones.filter(fecha_programada__lte=fecha_hasta)
    else:
        fecha_hasta = ""

    page_obj, parametros = paginar(
        request, programaciones, filas_por_pagina(request, 50)
    )

    return render(
        request,
        "inventario/mantenimientos_programados_lista.html",
        {
            "programaciones": page_obj.object_list,
            "page_obj": page_obj,
            "parametros": parametros,
            "total_resultados": page_obj.paginator.count,
            "estado_seleccionado": estado,
            "busqueda": busqueda,
            "tipo_equipo_seleccionado": tipo_equipo,
            "tipo_seleccionado": tipo,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "tipos_equipo": Equipo.Tipo.choices,
            "tipos_mantenimiento": MantenimientoEquipo.Tipo.choices,
            "hay_filtros": any([
                busqueda, tipo_equipo, tipo, fecha_desde, fecha_hasta,
                estado != MantenimientoProgramado.Estado.PROGRAMADO,
            ]),
            "hoy": timezone.localdate(),
            "pestana": "programados",
            "total_equipos": Equipo.objects.filter(activo=True).count(),
        },
    )


@login_required
@requiere_permiso("programar")
def mantenimiento_programado_crear(request):
    if not pide_modal(request):
        return abrir_en_ventana(request, "programar")

    equipo_fijo = equipo_fijo_de(request)

    if request.method == "POST":
        formulario = MantenimientoProgramadoForm(request.POST)

        if formulario.is_valid():
            programacion = formulario.save(commit=False)
            programacion.creado_por = request.user
            programacion.save()

            messages.success(request, "El mantenimiento quedó programado.")

            # El panel recarga la lista y muestra el mensaje.
            return JsonResponse({"ok": True})
    else:
        formulario = MantenimientoProgramadoForm(
            initial={"equipo": equipo_de_la_url(request)}
        )

    contexto = contexto_modal(
        formulario, equipo_fijo, "Programar mantenimiento",
        reverse("inventario:mantenimiento_programado_crear"), "programar",
    )

    return render(request, "inventario/_mantenimiento_modal.html", contexto)


@login_required
@requiere_permiso("mantenimientos")
def mantenimiento_programado_completar(request, programacion_id):
    if not pide_modal(request):
        return abrir_completar_en_ventana(programacion_id)

    with transaction.atomic():
        programacion = get_object_or_404(
            MantenimientoProgramado.objects.select_for_update(),
            pk=programacion_id,
        )

        if programacion.estado != MantenimientoProgramado.Estado.PROGRAMADO:
            messages.error(
                request,
                "Esta programación ya fue completada o cancelada.",
            )
            # El panel recarga la lista y muestra el mensaje.
            return JsonResponse({"ok": False})

        if programacion.intervencion_realizada_id:
            messages.error(
                request,
                "La programación ya tiene una intervención vinculada.",
            )
            # El panel recarga la lista y muestra el mensaje.
            return JsonResponse({"ok": False})

        datos_iniciales = {
            "equipo": programacion.equipo_id,
            "tipo": programacion.tipo,
            "motivo": programacion.descripcion,
            "observaciones": programacion.observaciones,
            # Lo que se marcó al programar queda marcado al completar.
            "actividades_preventivas": (
                programacion.actividades
                if programacion.tipo == MantenimientoEquipo.Tipo.PREVENTIVO else []
            ),
            "componentes_intervenidos": (
                programacion.actividades
                if programacion.tipo == MantenimientoEquipo.Tipo.CORRECTIVO else []
            ),
            "fecha_intervencion": timezone.localtime().strftime(
                "%Y-%m-%dT%H:%M"
            ),
        }

        if request.method == "POST":
            formulario = MantenimientoEquipoForm(
                request.POST,
                initial=datos_iniciales,
            )
        else:
            formulario = MantenimientoEquipoForm(
                initial=datos_iniciales,
            )

        # El equipo y el tipo quedan fijados a la programación original.
        formulario.fields["equipo"].disabled = True
        formulario.fields["tipo_equipo"].disabled = True
        formulario.fields["tipo"].disabled = True

        if request.method == "POST" and formulario.is_valid():
            mantenimiento = formulario.save(commit=False)
            mantenimiento.registrado_por = request.user
            mantenimiento.save()

            programacion.intervencion_realizada = mantenimiento
            programacion.estado = (
                MantenimientoProgramado.Estado.COMPLETADO
            )
            programacion.save(
                update_fields=[
                    "intervencion_realizada",
                    "estado",
                ]
            )

            messages.success(
                request,
                "La intervención quedó registrada y la programación fue completada.",
            )
            # El panel recarga la lista y muestra el mensaje.
            return JsonResponse({"ok": True})

    contexto = contexto_modal(
        formulario, programacion.equipo, "Completar mantenimiento programado",
        reverse(
            "inventario:mantenimiento_programado_completar",
            args=[programacion.pk],
        ),
        "completar",
    )

    return render(request, "inventario/_mantenimiento_modal.html", contexto)


@login_required
@requiere_permiso("programar")
def mantenimiento_programado_cancelar(request, programacion_id):
    if request.method != "POST":
        return redirect("inventario:mantenimientos_programados_lista")

    with transaction.atomic():
        programacion = get_object_or_404(
            MantenimientoProgramado.objects.select_for_update(),
            pk=programacion_id,
        )

        if programacion.estado != MantenimientoProgramado.Estado.PROGRAMADO:
            messages.error(
                request,
                "Solo se pueden cancelar programaciones pendientes.",
            )
        else:
            programacion.estado = (
                MantenimientoProgramado.Estado.CANCELADO
            )
            programacion.save(update_fields=["estado"])

            messages.success(
                request,
                "La programación fue cancelada correctamente.",
            )

    return redirect("inventario:mantenimientos_programados_lista")


@login_required
@xframe_options_sameorigin
@requiere_permiso("entregas")
def asignacion_crear(request):
    """Registra una entrega de radio o muestra el formulario dentro de Equipos."""
    if request.method != "POST":
        if request.GET.get("embed") == "1":
            radio_id = request.GET.get("radio", "")
            radio = (
                Radio.objects.filter(pk=radio_id).first()
                if radio_id.isdigit()
                else None
            )
            formulario = AsignacionRadioForm(
                initial={"radio": radio} if radio else None
            )
            return render(request, "inventario/asignacion_form.html", {
                "formulario": formulario,
                "titulo": "Registrar entrega de radio",
                "clausula": CLAUSULA_CONFIDENCIALIDAD,
            })
        return redirect("inventario:equipos_lista")

    radio_id = request.POST.get("radio", "")
    radio = Radio.objects.filter(pk=radio_id).first() if radio_id.isdigit() else None
    if radio is None:
        messages.error(request, "Elige el radio desde su ficha.")
        return redirect("inventario:equipos_lista")

    formulario = AsignacionRadioForm(request.POST)

    if formulario.is_valid():
        radio = formulario.cleaned_data["radio"]

        if AsignacionRadio.objects.filter(
            radio=radio,
            estado=AsignacionRadio.Estado.ASIGNADO,
        ).exists():
            formulario.add_error(
                "radio",
                "Este radio sigue asignado. "
                "Registra primero su devolución.",
            )
        else:
            try:
                with transaction.atomic():
                    asignacion = formulario.save(commit=False)
                    asignacion.entregado_por = request.user
                    asignacion.estado = AsignacionRadio.Estado.ASIGNADO
                    asignacion.save()

                    radio.coordinador_zona = asignacion.coordinador_zona
                    radio.cedula_funcionario = asignacion.cedula_funcionario
                    radio.cliente_asignado = asignacion.cliente_asignado
                    radio.puesto_asignado = asignacion.puesto_asignado
                    radio.save(
                        update_fields=[
                            "coordinador_zona",
                            "cedula_funcionario",
                            "cliente_asignado",
                            "puesto_asignado",
                            "actualizado_en",
                        ]
                    )
            except IntegrityError:
                formulario.add_error(
                    "radio",
                    "El radio ya tiene una asignación activa. "
                    "Actualiza la página y verifica su estado.",
                )
            else:
                messages.success(
                    request, "La entrega del radio quedó registrada."
                )
                if request.POST.get("pestanas_radio") == "1":
                    return _volver_a_pestana_radio(radio.pk, "entregas")
                return _volver_a_equipos(radio.pk)

    if request.POST.get("pestanas_radio") == "1":
        return render(request, "inventario/asignacion_form.html", {
            "formulario": formulario,
            "titulo": "Registrar entrega de radio",
            "clausula": CLAUSULA_CONFIDENCIALIDAD,
        })
    messages.error(request, "No se pudo registrar la entrega. "
                  + formulario.errors.as_text().replace("\n", " "))
    return _volver_a_equipos(radio.pk)


@login_required
@xframe_options_sameorigin
def asignacion_acta(request, asignacion_id):
    asignacion = get_object_or_404(
        AsignacionRadio.objects.select_related("radio", "entregado_por"),
        pk=asignacion_id,
    )
    return render(request, "inventario/asignacion_acta.html", {
        "asignacion": asignacion,
        "clausula": CLAUSULA_CONFIDENCIALIDAD,
    })


@login_required
@xframe_options_sameorigin
@requiere_permiso("entregas")
def asignacion_devolver(request, asignacion_id):
    if request.method != "POST":
        return redirect("inventario:equipos_lista")

    with transaction.atomic():
        asignacion = get_object_or_404(
            AsignacionRadio.objects.select_for_update(),
            pk=asignacion_id,
            estado=AsignacionRadio.Estado.ASIGNADO,
        )

        radio = Radio.objects.select_for_update().get(
            pk=asignacion.radio_id
        )

        asignacion.estado = AsignacionRadio.Estado.DEVUELTO
        asignacion.fecha_devolucion = timezone.now()
        asignacion.recibido_por = request.user
        asignacion.observaciones_devolucion = (
            request.POST.get("observaciones_devolucion", "").strip()
        )
        asignacion.save(
            update_fields=[
                "estado",
                "fecha_devolucion",
                "recibido_por",
                "observaciones_devolucion",
                "actualizado_en",
            ]
        )

        # No borrar información si los datos actuales del radio
        # ya no corresponden a esta asignación.
        if (
            radio.cedula_funcionario == asignacion.cedula_funcionario
            and radio.cliente_asignado == asignacion.cliente_asignado
            and radio.puesto_asignado == asignacion.puesto_asignado
            and radio.coordinador_zona == asignacion.coordinador_zona
        ):
            radio.coordinador_zona = ""
            radio.cedula_funcionario = ""
            radio.cliente_asignado = ""
            radio.puesto_asignado = ""
            radio.save(
                update_fields=[
                    "coordinador_zona",
                    "cedula_funcionario",
                    "cliente_asignado",
                    "puesto_asignado",
                    "actualizado_en",
                ]
            )

    messages.success(
        request,
        "La devolución del radio quedó registrada.",
    )
    if request.POST.get("pestanas_radio") == "1":
        return _volver_a_pestana_radio(radio.pk, "entregas")
    return _volver_a_equipos(radio.pk)


