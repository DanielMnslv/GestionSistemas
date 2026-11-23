#!/usr/bin/env bash
# Actualiza JANO Inventario en el servidor Linux (Plesk) con lo último de GitHub.
#
# Flujo de trabajo:
#   1. Los cambios se hacen y se prueban en el equipo local (manage.py test).
#   2. Se suben a GitHub (rama main).
#   3. En el servidor, dentro de la carpeta de la plataforma:   ./actualizar.sh
#
# Qué hace, en orden (si un paso falla, se detiene y no sigue):
#   1. Respalda la base SQLite en respaldos/antes_de_actualizar/ (conserva 30).
#      Va primero porque `migrate` cambia la base y no se puede deshacer.
#   2. Baja los cambios de GitHub (solo avance directo; si hay cambios hechos
#      a mano en el servidor, se detiene para no pisarlos).
#   3. Instala las dependencias (si el sitio tiene entorno virtual propio).
#   4. Aplica las migraciones, prepara los estilos y revisa la configuración.
#   5. Reinicia la aplicación (Passenger de Plesk o servicio de systemd).
#
# Variables opcionales:
#   PY=/ruta/a/python ./actualizar.sh        Python a usar (si no, lo busca).
#   SERVICIO=nombre ./actualizar.sh          Servicio de systemd (si no es Plesk).
#   SIN_RESPALDO=1 ./actualizar.sh           Omite el respaldo (no recomendado).
#
# Nunca toca el .env, la base de datos (salvo migrar) ni la carpeta media/.
set -euo pipefail

cd "$(dirname "$0")"
SERVICIO="${SERVICIO:-jano_inventario}"

echo "== Eligiendo el Python de la plataforma"
# Orden: el indicado en PY, el entorno virtual del sitio (.venv o venv) y,
# por último, el Python de Plesk (el mismo que usa Passenger).
if [ -n "${PY:-}" ]; then
    :
elif [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
elif [ -x venv/bin/python ]; then
    PY=venv/bin/python
elif [ -x /opt/plesk/python/3/bin/python3 ]; then
    PY=/opt/plesk/python/3/bin/python3
else
    PY=python3
fi
echo "Python: $PY"

if [ "${SIN_RESPALDO:-}" = "1" ]; then
    echo "== Respaldo omitido (SIN_RESPALDO=1)"
else
    echo "== Respaldando la base de datos"
    "$PY" manage.py respaldar_bd --destino respaldos/antes_de_actualizar --conservar 30
fi

echo "== Bajando cambios de GitHub"
ANTES="$(git rev-parse --short HEAD)"
git pull --ff-only

case "$PY" in
    .venv/*|venv/*)
        echo "== Instalando dependencias"
        "$PY" -m pip install -q -r requirements.txt
        ;;
esac

echo "== Aplicando cambios a la base de datos"
"$PY" manage.py migrate --noinput

echo "== Preparando estilos e imágenes"
"$PY" manage.py collectstatic --noinput -v 0

echo "== Revisando la configuración"
"$PY" manage.py check

echo "== Reiniciando la plataforma"
if [ -f passenger_wsgi.py ] || [ -d tmp ]; then
    mkdir -p tmp && touch tmp/restart.txt  # Plesk / Passenger
    echo "Reinicio solicitado a Passenger (Plesk)."
elif systemctl cat "${SERVICIO}.service" >/dev/null 2>&1; then
    sudo systemctl restart "$SERVICIO"
    echo "Reiniciado el servicio $SERVICIO."
else
    echo "No encontré cómo reiniciar. Hágalo en Plesk › Sitios web › Python › Reiniciar aplicación."
fi

echo "== Listo: $ANTES -> $(git log -1 --format='%h %s')"
