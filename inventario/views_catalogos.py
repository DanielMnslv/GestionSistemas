"""Catálogo de clientes y puestos de servicio."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import Cliente, Puesto, Vigilante
from .permisos import requiere_permiso
from .views import filas_por_pagina, paginar


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "nit"]
        labels = {"nit": "NIT"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class PuestoForm(forms.ModelForm):
    class Meta:
        model = Puesto
        fields = ["sede", "nombre"]
        labels = {"nombre": "Nombre del puesto"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


@login_required
def puestos_json(request):
    """Puestos activos de un cliente, para el formulario de entrega."""
    puestos = Puesto.objects.filter(
        activo=True, cliente_id=request.GET.get("cliente") or 0
    )
    return JsonResponse({
        "puestos": [{"id": p.pk, "texto": str(p)} for p in puestos]
    })


@login_required
def clientes_lista(request):
    clientes = Cliente.objects.annotate(
        total_puestos=Count("puestos", filter=Q(puestos__activo=True))
    )
    busqueda = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "activos")
    puestos = request.GET.get("puestos", "").strip()
    if busqueda:
        clientes = clientes.filter(
            Q(nombre__icontains=busqueda) | Q(nit__icontains=busqueda)
            | Q(puestos__nombre__icontains=busqueda)
            | Q(puestos__sede__icontains=busqueda)
        ).distinct()
    if estado == "activos":
        clientes = clientes.filter(activo=True)
    elif estado == "inactivos":
        clientes = clientes.filter(activo=False)
    else:
        estado = ""
    if puestos == "con":
        clientes = clientes.filter(total_puestos__gt=0)
    elif puestos == "sin":
        clientes = clientes.filter(total_puestos=0)
    else:
        puestos = ""
    formulario = ClienteForm()
    page_obj, parametros = paginar(
        request, clientes.order_by("nombre"), filas_por_pagina(request, 10)
    )
    return render(request, "inventario/clientes_lista.html", {
        "pestana": "clientes",
        "total_clientes": Cliente.objects.count(),
        "total_vigilantes": Vigilante.objects.count(),
        "clientes": page_obj.object_list,
        "page_obj": page_obj,
        "parametros": parametros,
        "total_resultados": page_obj.paginator.count,
        "busqueda": busqueda,
        "estado_seleccionado": estado,
        "puestos_seleccionado": puestos,
        "formulario": formulario,
    })


@login_required
@requiere_permiso("entregas")
def cliente_crear(request):
    formulario = ClienteForm(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        cliente = formulario.save()
        messages.success(request, f"Se creó el cliente {cliente}.")
        return redirect("inventario:cliente_detalle", cliente.pk)
    messages.error(request, "Escribe el nombre del cliente.")
    return redirect("inventario:clientes_lista")


@login_required
def cliente_detalle(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    return render(request, "inventario/cliente_detalle.html", {
        "cliente": cliente,
        "puestos": cliente.puestos.order_by("-activo", "sede", "nombre"),
        "formulario": PuestoForm(),
    })


@login_required
@requiere_permiso("entregas")
def puesto_crear(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    formulario = PuestoForm(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        puesto = formulario.save(commit=False)
        puesto.cliente = cliente
        puesto.save()
        messages.success(request, f"Se creó el puesto {puesto}.")
    elif request.method == "POST":
        messages.error(request, "Escribe el nombre del puesto.")
    return redirect("inventario:cliente_detalle", pk)


@login_required
@requiere_permiso("entregas")
def cliente_cambiar_estado(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == "POST":
        cliente.activo = not cliente.activo
        cliente.save(update_fields=["activo"])
        messages.success(
            request, f"El cliente quedó {'activo' if cliente.activo else 'inactivo'}."
        )
    return redirect("inventario:cliente_detalle", pk)


@login_required
@requiere_permiso("entregas")
def puesto_cambiar_estado(request, pk):
    puesto = get_object_or_404(Puesto, pk=pk)
    if request.method == "POST":
        puesto.activo = not puesto.activo
        puesto.save(update_fields=["activo"])
    return redirect("inventario:cliente_detalle", puesto.cliente_id)
