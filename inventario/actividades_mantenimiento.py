"""Qué se revisa en el mantenimiento de cada tipo de equipo.

Los formularios de "Programar mantenimiento" y "Registrar intervención"
muestran, según el tipo de equipo y el tipo de mantenimiento elegidos:
- preventivo: las actividades de la rutina de ese equipo;
- correctivo: las piezas o partes que se intervinieron.

Las claves se guardan en la base (listas JSON), así que no se renombran: si
una actividad deja de usarse se quita de aquí, y los registros viejos la
siguen mostrando con su clave.
"""
from .models import Equipo

T = Equipo.Tipo

# Los 8 tipos de equipo que maneja TIC, en el orden del menú.
TIPOS_EQUIPO = [
    (T.COMPUTADOR, "Computador"),
    (T.RADIO, "Radio"),
    (T.TABLETA, "Tableta"),
    (T.IMPRESORA, "Impresora"),
    (T.ESCANER, "Escáner"),
    (T.GPS, "GPS"),
    (T.ALARMA, "Alarma"),
    (T.UPS, "UPS"),
]

OTROS = ("otros", "Otros")

PREVENTIVAS = {
    # Las claves del computador son las que ya tenía el formulario.
    T.COMPUTADOR: [
        ("componentes_internos", "Verificación de componentes internos"),
        ("limpieza_computador", "Limpieza física interna y externa"),
        ("pantalla_monitor", "Verificación de pantalla o monitor"),
        ("mouse_teclado", "Verificación de mouse y teclado"),
        ("fuente_adaptador", "Verificación de fuente o adaptador de energía"),
        ("perifericos_externos", "Verificación de periféricos externos"),
        ("software_computador", "Actualizaciones del sistema y antivirus"),
        ("prueba_funcionamiento", "Verificación de funcionamiento posterior al mantenimiento"),
    ],
    T.RADIO: [
        ("radio_limpieza", "Limpieza de carcasa, pantalla y contactos"),
        ("radio_bateria", "Revisión de batería (carga y autonomía)"),
        ("radio_antena", "Revisión de antena"),
        ("radio_cargador", "Revisión de base y cargador"),
        ("radio_controles", "Revisión de perillas, botones y PTT"),
        ("radio_audio", "Prueba de parlante y micrófono"),
        ("radio_programacion", "Verificación de canales y programación"),
        ("radio_prueba", "Prueba de transmisión y recepción"),
    ],
    T.TABLETA: [
        ("tableta_limpieza", "Limpieza de pantalla y carcasa"),
        ("tableta_tactil", "Prueba de pantalla táctil"),
        ("tableta_bateria", "Revisión de batería"),
        ("tableta_carga", "Revisión de puerto de carga y cargador"),
        ("tableta_software", "Actualización del sistema y aplicaciones"),
        ("tableta_prueba", "Prueba de funcionamiento"),
    ],
    T.IMPRESORA: [
        ("impresora_limpieza", "Limpieza interna (rodillos y bandejas)"),
        ("impresora_consumibles", "Revisión de tóner, tinta o cinta"),
        ("impresora_cabezal", "Revisión de cabezal o fusor"),
        ("impresora_papel", "Revisión de alimentación de papel"),
        ("impresora_conexion", "Revisión de conexión (red o USB)"),
        ("impresora_prueba", "Página de prueba"),
    ],
    T.ESCANER: [
        ("escaner_cristal", "Limpieza del cristal y el sensor"),
        ("escaner_rodillos", "Limpieza de rodillos y alimentador"),
        ("escaner_conexion", "Revisión de cable, fuente y conexión"),
        ("escaner_controlador", "Revisión del controlador y el software"),
        ("escaner_prueba", "Escaneo de prueba"),
    ],
    T.GPS: [
        ("gps_fisico", "Revisión del estado físico y la fijación"),
        ("gps_alimentacion", "Revisión de alimentación y cableado"),
        ("gps_antena", "Revisión de antenas GPS y GSM"),
        ("gps_sim", "Revisión de SIM y señal"),
        ("gps_plataforma", "Verificación del reporte en la plataforma"),
        ("gps_panico", "Prueba de botón de pánico y entradas"),
    ],
    T.ALARMA: [
        ("alarma_panel", "Revisión del panel y el teclado"),
        ("alarma_bateria", "Revisión de la batería de respaldo"),
        ("alarma_sensores", "Revisión de sensores y detectores"),
        ("alarma_sirena", "Prueba de sirena"),
        ("alarma_comunicacion", "Prueba de comunicación con la central"),
        ("alarma_prueba", "Prueba de disparo"),
    ],
    T.UPS: [
        ("ups_limpieza", "Limpieza y ventilación"),
        ("ups_baterias", "Revisión de baterías (voltaje y autonomía)"),
        ("ups_transferencia", "Prueba de transferencia"),
        ("ups_carga", "Revisión de la carga conectada"),
        ("ups_panel", "Revisión de panel y alarmas"),
    ],
}

CORRECTIVAS = {
    T.COMPUTADOR: [
        ("pc_disco", "Disco duro o de estado sólido"),
        ("pc_memoria", "Memoria RAM"),
        ("pc_board", "Tarjeta madre"),
        ("pc_fuente", "Fuente o cargador"),
        ("pc_pantalla", "Pantalla"),
        ("pc_teclado", "Teclado o mouse"),
        ("pc_software", "Sistema operativo o software"),
        ("pc_red", "Red o conectividad"),
    ],
    T.RADIO: [
        ("radio_c_bateria", "Batería"),
        ("radio_c_antena", "Antena"),
        ("radio_c_cargador", "Base o cargador"),
        ("radio_c_pantalla", "Pantalla"),
        ("radio_c_controles", "Perillas, botones o PTT"),
        ("radio_c_audio", "Parlante o micrófono"),
        ("radio_c_carcasa", "Carcasa"),
        ("radio_c_programacion", "Programación"),
    ],
    T.TABLETA: [
        ("tableta_c_pantalla", "Pantalla o táctil"),
        ("tableta_c_bateria", "Batería"),
        ("tableta_c_carga", "Puerto de carga o cargador"),
        ("tableta_c_software", "Sistema o aplicaciones"),
        ("tableta_c_carcasa", "Carcasa"),
    ],
    T.IMPRESORA: [
        ("impresora_c_alimentacion", "Rodillos o alimentación de papel"),
        ("impresora_c_cabezal", "Cabezal o fusor"),
        ("impresora_c_consumibles", "Tóner, tinta o cinta"),
        ("impresora_c_tarjeta", "Tarjeta lógica"),
        ("impresora_c_conexion", "Conectividad"),
    ],
    T.ESCANER: [
        ("escaner_c_sensor", "Cristal o sensor"),
        ("escaner_c_rodillos", "Rodillos o alimentador"),
        ("escaner_c_fuente", "Cable o fuente"),
        ("escaner_c_controlador", "Controlador o software"),
    ],
    T.GPS: [
        ("gps_c_equipo", "Equipo GPS"),
        ("gps_c_antena", "Antena"),
        ("gps_c_cableado", "Cableado o alimentación"),
        ("gps_c_sim", "SIM"),
        ("gps_c_configuracion", "Configuración"),
    ],
    T.ALARMA: [
        ("alarma_c_panel", "Panel"),
        ("alarma_c_teclado", "Teclado"),
        ("alarma_c_sensores", "Sensores"),
        ("alarma_c_sirena", "Sirena"),
        ("alarma_c_bateria", "Batería"),
        ("alarma_c_comunicador", "Comunicador"),
    ],
    T.UPS: [
        ("ups_c_baterias", "Baterías"),
        ("ups_c_tarjeta", "Tarjeta de control"),
        ("ups_c_ventilador", "Ventilador"),
        ("ups_c_salidas", "Tomas o salidas"),
    ],
}


def _choices(catalogo):
    """Todas las opciones, sin repetir, con "Otros" al final."""
    vistas, salida = set(), []
    for opciones in catalogo.values():
        for clave, texto in opciones:
            if clave not in vistas:
                vistas.add(clave)
                salida.append((clave, texto))
    return salida + [OTROS]


CHOICES_PREVENTIVAS = _choices(PREVENTIVAS)
CHOICES_CORRECTIVAS = _choices(CORRECTIVAS)
TEXTOS = dict(CHOICES_PREVENTIVAS + CHOICES_CORRECTIVAS)


def tipo_de_clave(catalogo):
    """{clave: tipo de equipo} para marcar cada casilla en el formulario."""
    return {clave: tipo for tipo, opciones in catalogo.items() for clave, _ in opciones}


def claves_validas(catalogo, tipo_equipo):
    """Claves de ``catalogo`` permitidas para ``tipo_equipo`` (incluye "Otros")."""
    return {c for c, _ in catalogo.get(tipo_equipo, [])} | {OTROS[0]}


def textos(claves):
    """Convierte una lista de claves en sus textos visibles."""
    return [TEXTOS.get(c, c) for c in claves or []]
