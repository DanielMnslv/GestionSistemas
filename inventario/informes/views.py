from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import render
from django.urls import reverse

from ..permisos import puede
from .exportacion import exportar_pdf, exportar_xlsx, formatear_valor, tono_texto
from .registro import informes_por_categoria, obtener_informe

POR_PAGINA_OPCIONES = (10, 25, 50, 100)
POR_PAGINA_INICIAL = 25
CLASE_TONO = {"green": "mant-vigente", "amber": "mant-proximo", "red": "mant-vencido"}


def _informe(clave):
    try:
        return obtener_informe(clave)
    except KeyError:
        raise Http404("Informe no encontrado.")


def _puede_ver(usuario, informe):
    return informe.requiere_permiso is None or puede(usuario, informe.requiere_permiso)


def _campos_filtros(informe, valores):
    campos = []
    for filtro in informe.filtros:
        valor = valores.get(filtro.clave)
        if filtro.tipo == "date":
            valor = valor.isoformat() if valor else ""
        campos.append({
            "clave": filtro.clave, "etiqueta": filtro.etiqueta, "tipo": filtro.tipo,
            "opciones": filtro.opciones, "ayuda": filtro.ayuda,
            "valor": valor if valor is not None else "",
        })
    return campos


def _consulta_filtros(request, informe):
    """Parámetros de los filtros (sin la página) para armar los enlaces."""
    return urlencode([(f.clave, request.GET[f.clave]) for f in informe.filtros if request.GET.get(f.clave)])


@login_required
def inicio_informes(request):
    categorias = []
    for nombre, lista in informes_por_categoria():
        visibles = [i for i in lista if _puede_ver(request.user, i)]
        if visibles:
            categorias.append((nombre, visibles))
    return render(request, "inventario/informes_inicio.html", {
        "categorias": categorias,
        "total_informes": sum(len(lista) for _, lista in categorias),
    })


@login_required
def vista_previa(request, clave):
    informe = _informe(clave)
    if not _puede_ver(request.user, informe):
        return HttpResponseForbidden("No tienes permiso para consultar este informe.")
    valores = informe.validar_filtros(request.GET)
    filas = informe.obtener_filas(valores, request.user)

    try:
        por_pagina = int(request.GET.get("por_pagina", POR_PAGINA_INICIAL))
    except ValueError:
        por_pagina = POR_PAGINA_INICIAL
    if por_pagina not in POR_PAGINA_OPCIONES:
        por_pagina = POR_PAGINA_INICIAL
    page_obj = Paginator(filas, por_pagina).get_page(request.GET.get("page"))

    filas_pantalla = []
    for fila in page_obj.object_list:
        celdas = []
        for columna in informe.columnas:
            texto = formatear_valor(fila.get(columna.clave))
            tono = tono_texto(texto) if columna.tono and texto else ""
            celdas.append({"texto": texto, "clase": CLASE_TONO.get(tono, ""),
                           "alinear": columna.alinear, "titulo": columna.titulo})
        filas_pantalla.append(celdas)

    consulta = _consulta_filtros(request, informe)
    sufijo = f"?{consulta}" if consulta else ""
    parametros = "&".join(p for p in (
        consulta, f"por_pagina={por_pagina}" if por_pagina != POR_PAGINA_INICIAL else "") if p)
    return render(request, "inventario/informe_detalle.html", {
        "informe": informe, "campos": _campos_filtros(informe, valores),
        "columnas": informe.columnas, "filas": filas_pantalla, "page_obj": page_obj,
        "parametros": parametros, "total_filas": len(filas),
        "cifras": [(t, formatear_valor(v)) for t, v in informe.resumen(filas)],
        "aviso": informe.aviso(valores, filas), "hay_filtros": bool(consulta),
        "por_pagina": por_pagina, "por_pagina_opciones": POR_PAGINA_OPCIONES,
        "excel_url": reverse("inventario:informe_excel", args=[clave]) + sufijo,
        "pdf_url": reverse("inventario:informe_pdf", args=[clave]) + sufijo,
        "limpiar_url": reverse("inventario:informe_detalle", args=[clave]),
    })


def _exportar(request, clave, exportador):
    informe = _informe(clave)
    if not _puede_ver(request.user, informe):
        return HttpResponseForbidden("No tienes permiso para exportar este informe.")
    valores = informe.validar_filtros(request.GET)
    filas = informe.obtener_filas(valores, request.user)
    return exportador(informe, filas, valores, request.user)


@login_required
def exportar_informe_excel(request, clave):
    return _exportar(request, clave, exportar_xlsx)


@login_required
def exportar_informe_pdf(request, clave):
    return _exportar(request, clave, exportar_pdf)
