"""Módulo de Usuarios: personas, equipos a cargo y paz y salvo."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .estado_mantenimiento import ESTADOS, equipos_con_estado, hoy_colombia
from .models import (
    AsignacionEquipo,
    AsignacionRadio,
    Equipo,
    Funcionario,
    ItemRetiro,
    RetiroFuncionario,
)
from .permisos import puede, requiere_permiso
from .personas import (
    cancelar_retiro,
    conteos_por_cedula,
    emitir_paz_y_salvo,
    equipos_a_cargo,
    iniciar_retiro,
    resumen_retiro,
    retiro_en_proceso,
    sincronizar_items,
    validar_item,
)


# Orden y nombre corto de cada tipo para las columnas e iconos.
TIPOS_CORTOS = [
    (Equipo.Tipo.COMPUTADOR, "PC", "monitor"),
    (Equipo.Tipo.RADIO, "Radios", "radio"),
    (Equipo.Tipo.GPS, "GPS", "map"),
    (Equipo.Tipo.TABLETA, "Tabletas", "box"),
    (Equipo.Tipo.IMPRESORA, "Impresoras", "file"),
]


class FuncionarioForm(forms.ModelForm):
    """Registro y edición de un funcionario: nombre, cédula, cargo y correo."""
    class Meta:
        model = Funcionario
        fields = ["nombre_completo", "cedula", "cargo", "correo"]
        labels = {
            "nombre_completo": "Nombre completo", "cedula": "Cédula",
            "cargo": "Cargo", "correo": "Correo",
        }

    def clean_cedula(self):
        """Quita los espacios de los extremos de la cédula."""
        return self.cleaned_data["cedula"].strip()

    def clean_nombre_completo(self):
        """Deja el nombre en mayúsculas y con un solo espacio entre palabras."""
        return " ".join(self.cleaned_data["nombre_completo"].split()).upper()


class RetiroForm(forms.ModelForm):
    """Inicio del retiro de un funcionario: motivo, fecha y observaciones."""
    class Meta:
        model = RetiroFuncionario
        fields = ["motivo", "fecha_retiro", "observaciones"]
        labels = {
            "motivo": "Motivo", "fecha_retiro": "Fecha de retiro",
            "observaciones": "Observaciones",
        }
        widgets = {
            "fecha_retiro": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }


def _tipos_de(conteo):
    """Chips por tipo para una fila: [(etiqueta, icono, n)]."""
    chips = []
    otros = 0
    conocidos = {t for t, _, _ in TIPOS_CORTOS}
    for tipo, corto, icono in TIPOS_CORTOS:
        if conteo.get(tipo):
            chips.append({"tipo": tipo, "etiqueta": corto, "icono": icono, "n": conteo[tipo]})
    for tipo, n in conteo.items():
        if tipo not in conocidos:
            otros += n
    if otros:
        chips.append({"tipo": "", "etiqueta": "Otros", "icono": "box", "n": otros})
    return chips


@login_required
def personas_lista(request):
    """Lista de funcionarios con búsqueda, cuántos equipos tiene cada uno y si
    tiene un retiro en proceso.
    """
    conteos = conteos_por_cedula()
    en_retiro = set(
        RetiroFuncionario.objects.filter(
            estado=RetiroFuncionario.Estado.EN_PROCESO
        ).values_list("funcionario_id", flat=True)
    )

    q = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "activos")
    con = request.GET.get("equipos", "")
    tipo = request.GET.get("tipo", "")

    personas = Funcionario.objects.all()
    if q:
        personas = personas.filter(
            Q(nombre_completo__icontains=q) | Q(cedula__icontains=q) | Q(cargo__icontains=q)
        )

    total_activos = Funcionario.objects.filter(activo=True).count()
    filas = []
    for p in personas:
        conteo = conteos.get(p.cedula.strip(), {})
        total = sum(conteo.values())
        retiro = p.pk in en_retiro
        if estado == "activos" and not p.activo:
            continue
        if estado == "retiro" and not retiro:
            continue
        if estado == "inactivos" and p.activo:
            continue
        if con == "con" and not total:
            continue
        if con == "sin" and total:
            continue
        if tipo and not conteo.get(tipo):
            continue
        filas.append({"p": p, "total": total, "chips": _tipos_de(conteo), "retiro": retiro})

    con_equipos = sum(1 for p in Funcionario.objects.filter(activo=True) if conteos.get(p.cedula.strip()))
    return render(request, "personas/lista.html", {
        "filas": filas,
        "q": q, "estado": estado, "con": con, "tipo": tipo,
        "tipos": TIPOS_CORTOS,
        "kpi": {
            "activos": total_activos,
            "con_equipos": con_equipos,
            "en_retiro": len(en_retiro),
            "paz_y_salvo": RetiroFuncionario.objects.filter(
                estado=RetiroFuncionario.Estado.PAZ_Y_SALVO
            ).count(),
        },
        "n_filtros": bool(q) + (estado != "activos") + bool(con) + bool(tipo),
    })


@login_required
def persona_detalle(request, pk):
    """Ficha del funcionario: equipos a su cargo con su estado de mantenimiento,
    entregas, solicitudes de soporte y retiros.
    """
    persona = get_object_or_404(Funcionario, pk=pk)
    a_cargo = equipos_a_cargo(persona)
    con_estado = {
        e.pk: e for e in equipos_con_estado(
            Equipo.objects.filter(pk__in=[d["equipo"].pk for d in a_cargo])
        )
    }
    etiquetas = dict(ESTADOS)
    for d in a_cargo:
        e = con_estado.get(d["equipo"].pk)
        d["mant"] = getattr(e, "estado_mantenimiento", "")
        d["mant_txt"] = etiquetas.get(d["mant"], "")
        d["proximo"] = getattr(e, "proximo_mantenimiento", None)
        a = d["asignacion_radio"]
        d["lugar"] = (
            " · ".join(x for x in (a.cliente_asignado, a.puesto_asignado) if x)
            if a else d["equipo"].ubicacion
        )

    cedula = persona.cedula.strip()
    historial = [
        {"fecha": a.fecha_entrega, "devuelto": a.fecha_devolucion, "equipo": a.equipo,
         "estado": a.get_estado_display(), "vigente": a.estado == "ASIGNADO"}
        for a in AsignacionEquipo.objects.filter(
            Q(funcionario=persona) | Q(cedula_recibe=cedula)
        ).select_related("equipo")
    ] + [
        {"fecha": a.fecha_entrega, "devuelto": a.fecha_devolucion, "equipo": a.radio.equipo,
         "estado": a.get_estado_display(), "vigente": a.estado == "ASIGNADO",
         "lugar": a.puesto_asignado}
        for a in AsignacionRadio.objects.filter(
            cedula_funcionario=cedula, radio__equipo__isnull=False
        ).select_related("radio__equipo")
    ]
    historial.sort(key=lambda h: h["fecha"], reverse=True)

    conteo = {}
    for d in a_cargo:
        conteo[d["equipo"].tipo] = conteo.get(d["equipo"].tipo, 0) + 1

    return render(request, "personas/detalle.html", {
        "persona": persona,
        "a_cargo": a_cargo,
        "chips": _tipos_de(conteo),
        "historial": historial[:40],
        "n_historial": len(historial),
        "retiro": retiro_en_proceso(persona),
        "retiros": persona.retiros.all(),
        "form_retiro": RetiroForm(initial={"fecha_retiro": hoy_colombia()}),
    })


@login_required
@requiere_permiso("personas")
def persona_crear(request):
    """Registro de un funcionario nuevo."""
    formulario = FuncionarioForm(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        persona = formulario.save()
        messages.success(request, "La persona quedó registrada.")
        return redirect("inventario:persona_detalle", pk=persona.pk)
    return render(request, "personas/form.html", {"formulario": formulario, "persona": None})


@login_required
@requiere_permiso("personas")
def persona_editar(request, pk):
    """Edición de los datos de un funcionario."""
    persona = get_object_or_404(Funcionario, pk=pk)
    formulario = FuncionarioForm(request.POST or None, instance=persona)
    if request.method == "POST" and formulario.is_valid():
        formulario.save()
        messages.success(request, "Los datos quedaron actualizados.")
        return redirect("inventario:persona_detalle", pk=persona.pk)
    return render(request, "personas/form.html", {"formulario": formulario, "persona": persona})


@login_required
@requiere_permiso("retiros")
def retiro_iniciar(request, pk):
    """Inicia el proceso de retiro (paz y salvo) de un funcionario. Solo por POST.

    Si ya hay uno en proceso, lleva a ese.
    """
    persona = get_object_or_404(Funcionario, pk=pk)
    if request.method != "POST":
        return redirect("inventario:persona_detalle", pk=pk)
    actual = retiro_en_proceso(persona)
    if actual:
        return redirect("inventario:retiro_detalle", pk=actual.pk)
    formulario = RetiroForm(request.POST)
    if not formulario.is_valid():
        messages.error(request, "Revisa el motivo y la fecha del retiro.")
        return redirect("inventario:persona_detalle", pk=pk)
    retiro = iniciar_retiro(
        persona, formulario.cleaned_data["motivo"],
        formulario.cleaned_data["fecha_retiro"],
        formulario.cleaned_data["observaciones"], request.user,
    )
    messages.success(
        request,
        f"Retiro iniciado. TIC debe validar {retiro.items.count()} equipo(s) antes del paz y salvo.",
    )
    return redirect("inventario:retiro_detalle", pk=retiro.pk)


@login_required
def retiro_detalle(request, pk):
    """Detalle del retiro: lista de equipos por validar (devuelto o reasignado).

    Antes de mostrarla se sincroniza con los equipos que tiene a cargo hoy.
    """
    retiro = get_object_or_404(
        RetiroFuncionario.objects.select_related("funcionario", "creado_por", "cerrado_por"), pk=pk
    )
    sincronizar_items(retiro)
    items = retiro.items.select_related("equipo", "reasignado_a", "validado_por")
    otras = Funcionario.objects.filter(activo=True).exclude(pk=retiro.funcionario_id)
    return render(request, "personas/retiro.html", {
        "retiro": retiro,
        "items": items,
        "resumen": resumen_retiro(retiro),
        "resultados": [
            (v, l) for v, l in ItemRetiro.Resultado.choices if v != ItemRetiro.Resultado.PENDIENTE
        ],
        "personas": otras,
        "puede_validar": puede(request.user, "validar_retiro"),
        "puede_cerrar": puede(request.user, "retiros"),
    })


@login_required
@requiere_permiso("validar_retiro")
def retiro_item_validar(request, pk):
    """Valida un equipo del retiro: devuelto o reasignado a otro funcionario."""
    item = get_object_or_404(ItemRetiro.objects.select_related("retiro"), pk=pk)
    if request.method == "POST":
        reasignado = None
        if request.POST.get("reasignado_a"):
            reasignado = Funcionario.objects.filter(
                pk=request.POST["reasignado_a"], activo=True
            ).first()
        try:
            validar_item(
                item, request.POST.get("resultado", ""), request.user,
                request.POST.get("observaciones", "").strip(), reasignado,
            )
            messages.success(request, f"{item.equipo.placa}: validación registrada.")
        except ValueError as error:
            messages.error(request, str(error))
    return redirect(reverse("inventario:retiro_detalle", args=[item.retiro_id]) + f"#item-{item.pk}")


@login_required
@requiere_permiso("retiros")
def retiro_emitir(request, pk):
    """Emite el paz y salvo cuando todos los equipos están validados.

    El funcionario queda inactivo.
    """
    retiro = get_object_or_404(RetiroFuncionario, pk=pk)
    if request.method == "POST":
        try:
            emitir_paz_y_salvo(retiro, request.user)
            messages.success(request, "Paz y salvo emitido. La persona quedó inactiva.")
        except ValueError as error:
            messages.error(request, str(error))
    return redirect("inventario:retiro_detalle", pk=pk)


@login_required
@requiere_permiso("retiros")
def retiro_cancelar(request, pk):
    """Cancela un retiro en proceso."""
    retiro = get_object_or_404(RetiroFuncionario, pk=pk)
    if request.method == "POST":
        try:
            cancelar_retiro(retiro, request.user)
            messages.success(request, "El retiro quedó cancelado.")
        except ValueError as error:
            messages.error(request, str(error))
    return redirect("inventario:persona_detalle", pk=retiro.funcionario_id)


@login_required
def paz_y_salvo(request, pk):
    """Documento de paz y salvo, listo para imprimir."""
    retiro = get_object_or_404(
        RetiroFuncionario.objects.select_related("funcionario", "cerrado_por"),
        pk=pk, estado=RetiroFuncionario.Estado.PAZ_Y_SALVO,
    )
    return render(request, "personas/paz_y_salvo.html", {
        "retiro": retiro,
        "items": retiro.items.select_related("equipo", "reasignado_a", "validado_por"),
    })


@login_required
def retiros_lista(request):
    """Lista de retiros filtrada por estado (por defecto, en proceso)."""
    estado = request.GET.get("estado", "EN_PROCESO")
    retiros = RetiroFuncionario.objects.select_related("funcionario", "creado_por")
    if estado in RetiroFuncionario.Estado.values:
        retiros = retiros.filter(estado=estado)
    else:
        estado = ""
    filas = [{"r": r, "res": resumen_retiro(r)} for r in retiros.prefetch_related("items")[:200]]
    conteo = {
        v: RetiroFuncionario.objects.filter(estado=v).count()
        for v in RetiroFuncionario.Estado.values
    }
    return render(request, "personas/retiros.html", {
        "filas": filas, "estado": estado,
        "pestanas": [
            {"valor": v, "etiqueta": l, "total": conteo[v]}
            for v, l in RetiroFuncionario.Estado.choices
        ] + [{"valor": "todos", "etiqueta": "Todos", "total": sum(conteo.values())}],
    })
