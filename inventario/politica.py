"""Puntos de la verificación de la política de seguridad informática.

Son los mismos 15 puntos del formulario de Google (hoja VERIFICACION
POLITICA). La clave se guarda en VerificacionPolitica.respuestas.
"""

from datetime import date, timedelta

CUMPLE = "CUMPLE"
NO_CUMPLE = "NO CUMPLE"
NO_APLICA = "NO APLICA"
RESPUESTAS = [(CUMPLE, "Cumple"), (NO_CUMPLE, "No cumple"), (NO_APLICA, "No aplica")]

PUNTOS = [
    ("usuario_dominio", "¿Posee cuenta de usuario del servidor de datos (usuario de dominio)?"),
    ("usuario_activo", "¿El usuario está activo?"),
    ("acceso_servidor", "¿Posee acceso al servidor?"),
    ("contrasena_matriz", "¿La contraseña coincide con la matriz de usuarios?"),
    ("carpetas_sig", "¿El usuario tiene acceso a las carpetas del SIG en el servidor o en la plataforma SIG?"),
    ("acceso_restringido", "¿Tiene acceso restringido a la información de otros procesos?"),
    ("antivirus", "¿El computador tiene antivirus instalado y activado?"),
    ("software_licenciado", "¿El computador posee software licenciado y dichas licencias activas?"),
    ("instalacion_restringida", "¿El usuario tiene restringida la instalación de software?"),
    ("usb_desactivado", "¿Los puertos USB están desactivados para unidades de almacenamiento extraíble?"),
    ("bloqueo_inactividad", "¿Cuando el equipo queda desatendido (inactividad) se bloquea?"),
    ("navegacion_autorizada", "¿Los accesos dentro de los navegadores web son autorizados (verificar historiales y logs)?"),
    ("sin_informacion_personal", "¿No se tiene información personal dentro del computador?"),
    ("tiene_correo", "¿El usuario posee correo electrónico?"),
    ("correo_sin_prohibidos", "¿Cumple con no tener correos prohibidos en la bandeja de entrada, salida o enviados?"),
]

TEXTO = dict(PUNTOS)


def incumplimientos(respuestas):
    """Textos de los puntos marcados como NO CUMPLE."""
    return [TEXTO.get(clave, clave) for clave, valor in respuestas.items() if valor == NO_CUMPLE]


def normalizar_respuesta(valor):
    texto = " ".join(str(valor or "").upper().split())
    if texto.startswith("NO C"):
        return NO_CUMPLE
    if texto.startswith("NO A") or texto in ("N/A", "NA"):
        return NO_APLICA
    if texto.startswith("CUMPL") or texto == "SI":
        return CUMPLE
    return ""


# ---- Estado de cada computador frente a la verificación anual ----------
DIAS_PROXIMO = 30

SIN_VERIFICAR = "SIN_VERIFICAR"
VENCIDA = "VENCIDA"
INCUMPLE = "INCUMPLE"
PROXIMA = "PROXIMA"
AL_DIA = "AL_DIA"

# Del más urgente al menos urgente (orden de las tarjetas y de la lista).
ESTADOS = [
    (SIN_VERIFICAR, "Sin verificar"),
    (VENCIDA, "Vencida"),
    (INCUMPLE, "Con incumplimientos"),
    (PROXIMA, f"Vence en {DIAS_PROXIMO} días"),
    (AL_DIA, "Al día"),
]

# Clase de color (las mismas etiquetas del panel de mantenimientos).
CLASE_ESTADO = {
    SIN_VERIFICAR: "sin_mantenimiento",
    VENCIDA: "vencido",
    INCUMPLE: "pendiente",
    PROXIMA: "proximo",
    AL_DIA: "vigente",
}


def sumar_un_anio(fecha):
    try:
        return fecha.replace(year=fecha.year + 1)
    except ValueError:  # 29 de febrero
        return date(fecha.year + 1, 2, 28)


def estado_verificacion(ultima, n_incumplimientos, hoy):
    """(estado, vence) a partir de la fecha de la última verificación."""
    if ultima is None:
        return SIN_VERIFICAR, None
    vence = sumar_un_anio(ultima)
    if vence < hoy:
        return VENCIDA, vence
    if n_incumplimientos:
        return INCUMPLE, vence
    if vence <= hoy + timedelta(days=DIAS_PROXIMO):
        return PROXIMA, vence
    return AL_DIA, vence
