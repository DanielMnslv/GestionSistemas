"""Genera el PDF y el Excel de un informe."""
import re
from datetime import date, datetime
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone

from ..estado_mantenimiento import ZONA_COLOMBIA

AZUL = "#080D79"
LIMA = "#B6D336"
GRIS = "#5B6076"
BORDE = "#D7DBE8"
FONDO_TONO = {"green": "#E3F6EA", "amber": "#FEF0C7", "red": "#FDE3E1", "gray": "#EEF0F6"}
TEXTO_TONO = {"green": "#067647", "amber": "#B54708", "red": "#B42318", "gray": "#475467"}

_ROJO = ("vencid", "dañ", "baja", "no operativ", "error", "atrasad", "sin firma",
         "incumpl", "no cumple", "sin mantenimiento", "sin verificar", "sin antivirus",
         "sin fecha", "pendiente", "no reporta")
_AMBAR = ("regular", "vence en", "proxim", "parcial", "en prueba", "revis")
_VERDE = ("operativ", "vigente", "al día", "solucionad", "enviada", "reporta",
          "firmada", "completad", "cumple", "devuelto", "asignado")


def formatear_valor(valor):
    """Convierte un valor en texto para la tabla (fechas en hora de Colombia, Sí/No…)."""
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return timezone.localtime(valor, ZONA_COLOMBIA).strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    return str(valor)


def tono_texto(texto):
    """Tono de color (green, amber, red, gray) según el texto de un estado."""
    t = (texto or "").strip().lower()
    if not t:
        return ""
    if t == "activo":
        return "green"
    if t == "inactivo":
        return "gray"
    # "no operativo" y similares deben ganar sobre "operativo"
    if any(p in t for p in _ROJO):
        return "red"
    if any(p in t for p in _AMBAR):
        return "amber"
    if any(p in t for p in _VERDE):
        return "green"
    return "gray"


def _nombre_archivo(informe, extension):
    """Nombre del archivo descargado: ``<clave>_<AAAAMMDD_HHMM>.<extension>``."""
    return f"{informe.clave}_{timezone.localtime(timezone.now(), ZONA_COLOMBIA):%Y%m%d_%H%M}.{extension}"


def _quien(usuario):
    """Nombre de quien genera el informe."""
    if usuario is None:
        return ""
    return usuario.get_full_name() or usuario.get_username()


def _generado(usuario):
    """Texto "Generado el … por …" para el encabezado."""
    ahora = timezone.localtime(timezone.now(), ZONA_COLOMBIA)
    texto = f"Generado el {ahora:%d/%m/%Y a las %H:%M}"
    quien = _quien(usuario)
    return f"{texto} por {quien}" if quien else texto


def _limpio(texto):
    """Excel no admite caracteres de control."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", texto)


# ---------------------------------------------------------------- Excel
def exportar_xlsx(informe, filas, valores, usuario=None):
    """Genera el informe en Excel (.xlsx) con encabezado, filtros, totales y tabla.

    Devuelve la respuesta HTTP con el archivo para descargar.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    libro = Workbook()
    hoja = libro.active
    hoja.title = informe.titulo[:31].replace("/", "-").replace(":", "-")
    azul = PatternFill("solid", fgColor=AZUL.lstrip("#"))
    borde = Side(style="thin", color=BORDE.lstrip("#"))

    hoja.cell(1, 1, informe.titulo).font = Font(bold=True, size=14, color=AZUL.lstrip("#"))
    hoja.cell(2, 1, _generado(usuario)).font = Font(size=9, color=GRIS.lstrip("#"))
    fila_actual = 3
    filtros = informe.filtros_aplicados(valores)
    if filtros:
        hoja.cell(fila_actual, 1, "Filtros: " + "; ".join(f"{k}: {v}" for k, v in filtros)).font = Font(size=9)
        fila_actual += 1
    for titulo, valor in informe.resumen(filas):
        hoja.cell(fila_actual, 1, titulo).font = Font(bold=True, size=10)
        hoja.cell(fila_actual, 2, formatear_valor(valor)).alignment = Alignment(horizontal="left")
        fila_actual += 1
    fila_actual += 1

    encabezado = fila_actual
    for i, col in enumerate(informe.columnas, 1):
        c = hoja.cell(encabezado, i, col.titulo)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = azul
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    anchos = [len(c.titulo) for c in informe.columnas]
    for n, fila in enumerate(filas, encabezado + 1):
        for i, col in enumerate(informe.columnas, 1):
            texto = _limpio(formatear_valor(fila.get(col.clave)))
            c = hoja.cell(n, i, texto)
            c.alignment = Alignment(
                horizontal={"der": "right", "centro": "center"}.get(col.alinear, "left"),
                vertical="top", wrap_text=True)
            c.border = Border(bottom=borde)
            if col.tono and texto:
                tono = tono_texto(texto)
                c.fill = PatternFill("solid", fgColor=FONDO_TONO[tono].lstrip("#"))
                c.font = Font(bold=True, color=TEXTO_TONO[tono].lstrip("#"))
            anchos[i - 1] = max(anchos[i - 1], min(len(texto), 60))
    for i, ancho in enumerate(anchos, 1):
        hoja.column_dimensions[get_column_letter(i)].width = ancho + 3
    if filas:
        hoja.auto_filter.ref = f"A{encabezado}:{get_column_letter(len(informe.columnas))}{encabezado + len(filas)}"
    hoja.freeze_panes = hoja.cell(encabezado + 1, 1)
    hoja.sheet_view.showGridLines = False

    salida = BytesIO()
    libro.save(salida)
    respuesta = HttpResponse(
        salida.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{_nombre_archivo(informe, "xlsx")}"'
    return respuesta


# ------------------------------------------------------------------ PDF
def exportar_pdf(informe, filas, valores, usuario=None):
    """Genera el informe en PDF con los colores de JANO.

    Incluye encabezado, filtros aplicados, totales y la tabla; la orientación
    se elige según el número de columnas. Devuelve la respuesta HTTP con el
    archivo para descargar.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )
    from xml.sax.saxutils import escape

    columnas = informe.columnas_para_pdf
    horizontal = (informe.orientacion == "horizontal"
                  or (informe.orientacion is None and len(columnas) > 5))
    if informe.orientacion == "vertical":
        horizontal = False
    pagina = landscape(A4) if horizontal else A4
    margen = 12 * mm
    ancho_util = pagina[0] - 2 * margen
    azul, lima, gris = colors.HexColor(AZUL), colors.HexColor(LIMA), colors.HexColor(GRIS)

    fuente = 7.5 if len(columnas) > 7 else 8.5
    st_celda = ParagraphStyle("celda", fontName="Helvetica", fontSize=fuente, leading=fuente + 2)
    st_cab = ParagraphStyle("cab", fontName="Helvetica-Bold", fontSize=fuente, leading=fuente + 2,
                            textColor=colors.white)
    st_titulo = ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=azul)
    st_meta = ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5, leading=11, textColor=gris)
    alinea = {"izq": 0, "centro": 1, "der": 2}

    def parrafo(texto, estilo, alinear="izq", color=None, negrilla=False):
        """Párrafo con alineación, color y negrilla para una celda del PDF."""
        e = ParagraphStyle("x", parent=estilo, alignment=alinea[alinear])
        if color:
            e.textColor = colors.HexColor(color)
        if negrilla:
            e.fontName = "Helvetica-Bold"
        return Paragraph(escape(texto).replace("\n", "<br/>"), e)

    historia = [Paragraph(escape(informe.titulo), st_titulo), Spacer(1, 2)]
    meta = [informe.categoria, _generado(usuario)]
    historia.append(Paragraph(escape(" · ".join(meta)), st_meta))
    filtros = informe.filtros_aplicados(valores)
    if filtros:
        historia.append(Paragraph(escape("Filtros: " + "; ".join(f"{k}: {v}" for k, v in filtros)), st_meta))
    cifras = informe.resumen(filas)
    if cifras:
        historia.append(Spacer(1, 6))
        celdas = [[parrafo(str(formatear_valor(v)), st_titulo, "centro") for _, v in cifras],
                  [parrafo(t, st_meta, "centro") for t, _ in cifras]]
        tarjeta = Table(celdas, colWidths=[ancho_util / len(cifras)] * len(cifras))
        tarjeta.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDE)),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor(BORDE)),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F8FC")),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        historia.append(tarjeta)
    aviso = informe.aviso(valores, filas)
    if aviso:
        historia += [Spacer(1, 6), Paragraph(escape(aviso), st_meta)]
    historia.append(Spacer(1, 8))

    if not filas:
        historia.append(Paragraph("No hay registros con los filtros seleccionados.", st_meta))
    else:
        datos = [[parrafo(c.titulo, st_cab, c.alinear if c.alinear != "izq" else "izq") for c in columnas]]
        estilos = [
            ("BACKGROUND", (0, 0), (-1, 0), azul),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor(BORDE)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FC")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for n, fila in enumerate(filas, 1):
            linea = []
            for i, c in enumerate(columnas):
                texto = formatear_valor(fila.get(c.clave)) or ("—" if not c.tono else "")
                if c.tono and texto and texto != "—":
                    tono = tono_texto(texto)
                    estilos.append(("BACKGROUND", (i, n), (i, n), colors.HexColor(FONDO_TONO[tono])))
                    linea.append(parrafo(texto, st_celda, c.alinear, TEXTO_TONO[tono], True))
                else:
                    total = fila.get(informe.columnas[0].clave) == "TOTAL" or fila.get("tipo") == "TOTAL"
                    linea.append(parrafo(texto, st_celda, c.alinear, negrilla=total))
            datos.append(linea)
        pesos = [c.ancho for c in columnas]
        anchos = [ancho_util * p / sum(pesos) for p in pesos]
        tabla = Table(datos, colWidths=anchos, repeatRows=1)
        tabla.setStyle(TableStyle(estilos))
        historia.append(tabla)

    def pie(lienzo, doc):
        """Dibuja la franja superior y el pie de página con el número de página."""
        lienzo.saveState()
        lienzo.setFillColor(lima)
        lienzo.rect(0, pagina[1] - 4 * mm, pagina[0], 4 * mm, stroke=0, fill=1)
        lienzo.setFillColor(gris)
        lienzo.setFont("Helvetica", 7.5)
        lienzo.drawString(margen, 7 * mm, f"JANO Inventario · {informe.titulo}")
        lienzo.drawRightString(pagina[0] - margen, 7 * mm, f"Página {doc.page}")
        lienzo.restoreState()

    salida = BytesIO()
    SimpleDocTemplate(
        salida, pagesize=pagina, leftMargin=margen, rightMargin=margen,
        topMargin=margen + 3 * mm, bottomMargin=margen + 3 * mm,
        title=informe.titulo, author="JANO Inventario",
    ).build(historia, onFirstPage=pie, onLaterPages=pie)
    respuesta = HttpResponse(salida.getvalue(), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="{_nombre_archivo(informe, "pdf")}"'
    return respuesta
