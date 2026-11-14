"""Definición común de un informe: columnas, filtros y filas."""
from datetime import date


class Columna:
    """Columna de un informe: qué dato muestra, su título y cómo se ve en el PDF."""
    def __init__(self, clave, titulo, ancho=1, alinear="izq", tono=False):
        """Define la columna.

        Args:
            clave: nombre del dato en cada fila.
            titulo: encabezado visible.
            ancho: peso relativo del ancho en el PDF.
            alinear: "izq", "der" o "centro".
            tono: si es verdadero, el texto se pinta como insignia de color
                según su valor (bueno, regular, malo…).
        """
        self.clave = clave
        self.titulo = titulo
        self.ancho = ancho          # peso relativo del ancho en el PDF
        self.alinear = alinear      # izq, der o centro
        self.tono = tono            # pinta el valor según su estado


class Filtro:
    """Filtro de un informe que el usuario llena antes de verlo o exportarlo."""
    def __init__(self, clave, etiqueta, tipo="text", opciones=(), inicial=None, ayuda=""):
        """Define el filtro.

        Args:
            clave: nombre del parámetro en la URL.
            etiqueta: texto visible.
            tipo: "text", "select", "date" o "checkbox".
            opciones: pares (valor, etiqueta) para las listas.
            inicial: valor por defecto.
            ayuda: texto de ayuda bajo el campo.
        """
        self.clave = clave
        self.etiqueta = etiqueta
        self.tipo = tipo            # text, select, date, checkbox
        self.opciones = tuple(opciones)
        self.ayuda = ayuda
        if inicial is None:
            inicial = self.opciones[0][0] if tipo == "select" and self.opciones else ""
        self.inicial = inicial

    def leer(self, datos):
        """Lee y valida el valor del filtro desde los parámetros recibidos.

        Una opción que no está en la lista vuelve al valor inicial y una fecha
        mal escrita queda vacía, así una URL alterada no rompe el informe.
        """
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
        """Texto legible del valor elegido, para mostrarlo en el encabezado del PDF y Excel."""
        if self.tipo == "select":
            return dict(self.opciones).get(valor, valor)
        if self.tipo == "date":
            return valor.strftime("%d/%m/%Y") if valor else ""
        if self.tipo == "checkbox":
            return "Sí" if valor else ""
        return valor


class Informe:
    """Clase base de todos los informes.

    Cada informe define ``clave`` (para la URL), ``titulo``, ``categoria``,
    ``descripcion``, sus ``columnas`` y ``filtros``, y el método
    ``obtener_filas``. Opcionalmente: ``columnas_pdf`` (las que caben en el
    PDF), ``orientacion`` y ``requiere_permiso`` (acción de ``permisos.py``).

    Para agregar un informe nuevo: crea la clase en el archivo de su categoría
    y agrégala a la lista ``INFORMES`` de ese archivo (ver ``registro.py``).
    """
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
        """Lee todos los filtros y devuelve {clave: valor} ya validado."""
        return {f.clave: f.leer(datos) for f in self.filtros}

    def obtener_filas(self, valores, usuario=None):
        """Devuelve la lista de filas (diccionarios {clave_columna: valor}).

        Cada informe debe implementarlo.
        """
        raise NotImplementedError

    def resumen(self, filas):
        """Totales que se muestran arriba del informe, como pares (etiqueta, valor)."""
        return []

    def aviso(self, valores, filas):
        """Mensaje que se muestra arriba del informe. Vacío si no hay nada que avisar."""
        return ""

    @property
    def columnas_para_pdf(self):
        """Columnas que se imprimen en el PDF (todas si no se definió ``columnas_pdf``)."""
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
