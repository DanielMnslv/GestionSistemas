"""Definición común de un informe: columnas, filtros y filas."""
from datetime import date


class Columna:
    def __init__(self, clave, titulo, ancho=1, alinear="izq", tono=False):
        self.clave = clave
        self.titulo = titulo
        self.ancho = ancho          # peso relativo del ancho en el PDF
        self.alinear = alinear      # izq, der o centro
        self.tono = tono            # pinta el valor según su estado


class Filtro:
    def __init__(self, clave, etiqueta, tipo="text", opciones=(), inicial=None, ayuda=""):
        self.clave = clave
        self.etiqueta = etiqueta
        self.tipo = tipo            # text, select, date, checkbox
        self.opciones = tuple(opciones)
        self.ayuda = ayuda
        if inicial is None:
            inicial = self.opciones[0][0] if tipo == "select" and self.opciones else ""
        self.inicial = inicial

    def leer(self, datos):
        crudo = datos.get(self.clave)
        if self.tipo == "checkbox":
            return str(crudo or "").lower() in ("1", "true", "on", "si", "sí")
        if crudo is None:
            crudo = self.inicial
        crudo = str(crudo).strip()
        if self.tipo == "select":
            validos = {str(v) for v, _ in self.opciones}
            return crudo if crudo in validos else self.inicial
        if self.tipo == "date":
            try:
                return date.fromisoformat(crudo) if crudo else None
            except ValueError:
                return None
        return crudo

    def etiqueta_valor(self, valor):
        if self.tipo == "select":
            return dict(self.opciones).get(valor, valor)
        if self.tipo == "date":
            return valor.strftime("%d/%m/%Y") if valor else ""
        if self.tipo == "checkbox":
            return "Sí" if valor else ""
        return valor


class Informe:
    clave = ""
    titulo = ""
    categoria = ""
    descripcion = ""
    columnas = ()
    columnas_pdf = None             # claves que caben en el PDF; None = todas
    filtros = ()
    orientacion = None              # "horizontal", "vertical" o None (según columnas)
    requiere_permiso = None         # nombre de acción de permisos.py

    def validar_filtros(self, datos):
        return {f.clave: f.leer(datos) for f in self.filtros}

    def obtener_filas(self, valores, usuario=None):
        raise NotImplementedError

    def resumen(self, filas):
        return []

    def aviso(self, valores, filas):
        """Mensaje que se muestra arriba del informe. Vacío si no hay nada que avisar."""
        return ""

    @property
    def columnas_para_pdf(self):
        if not self.columnas_pdf:
            return list(self.columnas)
        por_clave = {c.clave: c for c in self.columnas}
        return [por_clave[k] for k in self.columnas_pdf]

    def filtros_aplicados(self, valores):
        """[(etiqueta, texto)] de los filtros que tienen valor, para el encabezado."""
        pares = []
        for f in self.filtros:
            valor = valores.get(f.clave)
            texto = f.etiqueta_valor(valor)
            if valor and texto:
                pares.append((f.etiqueta, str(texto)))
        return pares
