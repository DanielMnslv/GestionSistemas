"""Ubicación aproximada (municipio) de un puesto para el mapa del panel.

Los nombres de los puestos terminan casi siempre con el código DANE del
municipio (ej. "... VILLAVICENCIO 50001"); se usa el centro del municipio. Para agregar un municipio
nuevo, súmelo a MUNICIPIOS (código DANE: nombre, latitud, longitud).
"""
import re
import unicodedata
from collections import Counter, defaultdict

MUNICIPIOS = {
    "50001": ("Villavicencio", 4.1420, -73.6266),
    "50006": ("Acacías", 3.9870, -73.7577),
    "50110": ("Barranca de Upía", 4.5700, -72.9600),
    "50124": ("Cabuyaro", 4.2870, -72.7890),
    "50226": ("Cumaral", 4.2700, -73.4850),
    "50245": ("El Calvario", 4.3510, -73.7160),
    "50287": ("Fuente de Oro", 3.4640, -73.6150),
    "50313": ("Granada (Meta)", 3.5460, -73.7080),
    "50568": ("Puerto Gaitán", 4.3140, -72.0820),
    "50573": ("Puerto López", 4.0880, -72.9570),
    "50680": ("San Carlos de Guaroa", 3.7100, -73.2400),
    "50683": ("San Juan de Arama", 3.3380, -73.8790),
    "50686": ("San Juanito", 4.4560, -73.6760),
    "85001": ("Yopal", 5.3378, -72.3959),
    "85010": ("Aguazul", 5.1730, -72.5470),
    "85300": ("Sabanalarga (Casanare)", 4.8650, -73.0330),
    "85410": ("Tauramena", 5.0170, -72.7510),
    "81001": ("Arauca", 7.0847, -70.7591),
    "99001": ("Puerto Carreño", 6.1890, -67.4850),
    "99524": ("La Primavera", 5.4890, -70.4100),
    "99624": ("Santa Rosalía", 5.1400, -70.8600),
    "95001": ("San José del Guaviare", 2.5696, -72.6460),
    "95015": ("Calamar (Guaviare)", 1.9600, -72.6460),
    "95025": ("El Retorno", 2.3300, -72.6290),
    "95200": ("Miraflores (Guaviare)", 1.3380, -71.9500),
    "41132": ("Campoalegre", 2.6860, -75.3260),
    "73319": ("Guamo", 4.0300, -74.9700),
    "25307": ("Girardot", 4.3000, -74.8000),
    "25758": ("Sopó", 4.9060, -73.9430),
    "25754": ("Soacha", 4.5794, -74.2168),
    "85440": ("Villanueva (Casanare)", 4.6100, -72.9290),
    "85139": ("Maní", 4.8200, -72.2840),
    "11001": ("Bogotá", 4.7110, -74.0721),
    "54001": ("Cúcuta", 7.8939, -72.5078),
    "86568": ("Puerto Asís", 0.5000, -76.5000),
    "52001": ("Pasto", 1.2136, -77.2811),
    "52356": ("Ipiales", 0.8303, -77.6444),
    "52835": ("Tumaco", 1.7985, -78.8156),
    "19001": ("Popayán", 2.4448, -76.6147),
    "76001": ("Cali", 3.4516, -76.5320),
    "76054": ("Argelia (Valle)", 4.7270, -76.1200),
    "76100": ("Bolívar (Valle)", 4.3380, -76.1790),
    "76109": ("Buenaventura", 3.8801, -77.0312),
    "76111": ("Buga", 3.9010, -76.2980),
    "76113": ("Bugalagrande", 4.2100, -76.1590),
    "76130": ("Candelaria", 3.4130, -76.3480),
    "76243": ("El Águila", 4.9100, -76.0420),
    "76246": ("El Cairo", 4.7620, -76.2170),
    "76248": ("El Cerrito", 3.6850, -76.3170),
    "76275": ("Florida (Valle)", 3.3250, -76.2350),
    "76306": ("Ginebra", 3.7260, -76.2650),
    "76318": ("Guacarí", 3.7640, -76.3330),
    "76377": ("La Cumbre", 3.6500, -76.5700),
    "76400": ("La Unión (Valle)", 4.5340, -76.1050),
    "76403": ("La Victoria (Valle)", 4.5230, -76.0390),
    "76497": ("Obando", 4.5750, -75.9750),
    "76520": ("Palmira", 3.5394, -76.3036),
    "76606": ("Restrepo (Valle)", 3.8230, -76.5210),
    "76622": ("Roldanillo", 4.4100, -76.1530),
    "76736": ("Sevilla (Valle)", 4.2690, -75.9360),
    "76823": ("Toro", 4.6100, -76.0800),
    "76828": ("Trujillo", 4.2100, -76.3190),
    "76834": ("Tuluá", 4.0847, -76.1954),
    "76845": ("Ulloa", 4.7030, -75.7330),
    "76869": ("Vijes", 3.6990, -76.4410),
    "76892": ("Yumbo", 3.5850, -76.4950),
    "76895": ("Zarzal", 4.3930, -76.0780),
}

# Códigos mal digitados en los nombres de puestos -> código correcto.
ALIAS_CODIGOS = {
    "850001": "85001", "81002": "81001",
    "50658": "50568", "50569": "50568", "50570": "50568",
    "50574": "50573", "05313": "50313",
}

# Radios que están con la propia empresa (cliente "Seguridad Jano ..." en
# Sistemas, sede nueva, etc.): se ubican en la sede. CAMBIE aquí la ubicación
# real de la sede si no es Villavicencio.
SEDE_JANO = ("Sede Seguridad Jano", 4.1420, -73.6266)

# Respaldo cuando el nombre no trae código: palabra clave -> código.
PALABRAS = {
    "villavicencio": "50001", "acacias": "50006", "cabuyaro": "50124",
    "cumaral": "50226", "barranca de upia": "50110", "san carlos de guaroa": "50680",
    "puerto gaitan": "50568", "pto gaitan": "50568", "puerto lopez": "50573",
    "yopal": "85001", "arauca": "81001", "puerto carreno": "99001", "vichada": "99001",
    "guaviare": "95001", "cali": "76001", "yumbo": "76892",
    "potenza": "50001", "soacha": "25754", "villanueva": "85440", "mani casanare": "85139",
    "campoalegre": "41132", "sopo": "25758", "briceno": "25758",
}


def _norm(texto):
    """Texto sin tildes y en minúsculas."""
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def municipio_de(*textos):
    """Devuelve (nombre, lat, lng) del municipio que mencionan los textos, o None."""
    for t in textos:
        for codigo in re.findall(r"\b\d{5,6}\b", t or ""):
            codigo = ALIAS_CODIGOS.get(codigo, codigo)
            if codigo in MUNICIPIOS:
                return MUNICIPIOS[codigo]
    for t in textos:
        n = _norm(t)
        for palabra, codigo in PALABRAS.items():
            if re.search(r"\b" + palabra + r"\b", n):
                return MUNICIPIOS[codigo]
    return None


def _clave(texto):
    """Texto normalizado solo con letras y números, para comparar nombres."""
    return re.sub(r"[^a-z0-9]+", " ", _norm(texto)).strip()


class Localizador:
    """Ubica el puesto de una asignación de radio.

    Orden: municipio mencionado en el nombre; municipio del puesto del catálogo con el mismo nombre; y, por último,
    el municipio donde el cliente tiene la mayoría de sus puestos.
    Devuelve (lugar, latitud, longitud, exacta) o None.
    """

    def __init__(self, puestos):
        """puestos: filas (cliente, sede, nombre) del catálogo."""
        self.por_cliente_puesto, self.por_puesto = {}, defaultdict(list)
        cuentas = defaultdict(Counter)
        for cliente, sede, nombre in puestos:
            m = municipio_de(nombre, sede, cliente)
            dato = (m[0], m[1], m[2], False) if m else None
            if m:
                cuentas[_clave(cliente)][m] += 1
            self.por_cliente_puesto[(_clave(cliente), _clave(nombre))] = dato
            self.por_puesto[_clave(nombre)].append(dato)
        self.cliente_muni = {}
        for c, cnt in cuentas.items():
            (m, n), = cnt.most_common(1)
            if n / sum(cnt.values()) >= 0.6:
                self.cliente_muni[c] = (m[0], m[1], m[2], False)

    def de(self, cliente, puesto):
        """Ubicación (municipio, latitud, longitud, si es aproximada) de un cliente y puesto.

        Busca primero el municipio en el nombre del puesto o del cliente; los
        puestos de Seguridad JANO sin municipio van a la sede principal.
        """
        kc, kp = _clave(cliente), _clave(puesto)
        m = municipio_de(puesto, cliente)
        if not m and kc.startswith("seguridad jano"):
            return (SEDE_JANO[0], SEDE_JANO[1], SEDE_JANO[2], False)
        if m:
            return (m[0], m[1], m[2], False)
        if (kc, kp) in self.por_cliente_puesto and self.por_cliente_puesto[(kc, kp)]:
            return self.por_cliente_puesto[(kc, kp)]
        otros = {d for d in self.por_puesto.get(kp, []) if d}
        if len(otros) == 1:
            return otros.pop()
        if kc in self.cliente_muni:
            return self.cliente_muni[kc]
        if len(kc) >= 5:
            for c, dato in self.cliente_muni.items():
                if kc in c or c in kc:
                    return dato
        return None
