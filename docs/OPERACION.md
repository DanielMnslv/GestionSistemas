# JANO Inventario: operación

Tareas del día a día para quien administra la plataforma. La arquitectura está en [ARQUITECTURA.md](ARQUITECTURA.md) y la instalación en el hosting, en [INSTALAR_EN_SERVIDOR.md](INSTALAR_EN_SERVIDOR.md).

## 1. Dónde corre

| Instalación | Dirección | Servidor |
|---|---|---|
| Equipo local de TIC (Windows) | `http://127.0.0.1:8080` | Waitress, iniciado por `C:\JANOTEC_INTEGRACION\operacion\iniciar_plataformas.ps1` |
| Hosting (Ubuntu + Plesk) | `https://gestionsistemas.seguridadjano.com` | Phusion Passenger (aplicación Python de Plesk) |

En Windows, la configuración de producción está en `jano_inventario\.env.produccion`. **Nunca se sube a git.**

## 2. Iniciar, detener y reiniciar (Windows)

Scripts de `C:\JANOTEC_INTEGRACION\operacion\`. Se ejecutan con clic derecho › *Ejecutar con PowerShell*.

| Script | Qué hace |
|---|---|
| `iniciar_plataformas.ps1` | Ejecuta `collectstatic` y arranca JANO (8080) y Gestión TIC (8001) sin ventanas. Si una ya está corriendo, no la toca. |
| `detener_plataformas.ps1 -Puertos "8080"` | Detiene solo JANO. Sin `-Puertos`, detiene las dos. |

**Después de cambiar el código hay que reiniciar** (detener e iniciar): Waitress no recarga los cambios solo.

En Plesk se reinicia con **Sitios web › Python › Reiniciar aplicación**, o por SSH con `touch tmp/restart.txt`.

### SQLite del servidor Plesk

Django 5.2 requiere SQLite 3.31 o posterior. Si el Python de Plesk trae una
versión anterior, JANO puede usar `pysqlite3-binary` desde el entorno virtual o
desde `.runtime/vendor`, una carpeta privada del proyecto. Esto no reemplaza ni
actualiza el Python o SQLite global del servidor. En Linux, `manage.py`, WSGI y
ASGI cargan esta compatibilidad antes de importar Django.

## 3. Tareas programadas

**Ya programadas en el equipo local.** Se registran con `registrar_tareas.ps1` y se quitan con `registrar_tareas.ps1 -Quitar`.

| Tarea de Windows | Cuándo | Qué ejecuta |
|---|---|---|
| JANO - Iniciar plataformas | Al iniciar sesión | `iniciar_plataformas.ps1` |
| JANO - Respaldo diario | 6:00 p. m. | `respaldo_diario.ps1` → `manage.py respaldar_bd` (y el respaldo MySQL de Gestión TIC) |
| JANO - Alertas de mantenimiento | 8:00 a. m. | `alertas_mantenimiento.ps1` → `manage.py procesar_alertas_mantenimiento --enviar` |

**Existen como comando, pero aún no están programadas.** Conviene programarlas cuando se decida dónde corre la plataforma definitiva:

| Comando | Frecuencia sugerida |
|---|---|
| `manage.py procesar_alertas_antivirus --enviar` | Diaria |
| `manage.py cerrar_tickets_resueltos --confirmar` | Diaria. Cierra los casos resueltos hace más de 3 días sin respuesta del solicitante. |
| `manage.py enviar_eventos_integracion` y `manage.py procesar_eventos_gestion_tic` | Cada 5 minutos, si se usa la integración con Gestión TIC |

En Plesk se programan en **Herramientas › Tareas programadas** con el Python del entorno virtual del sitio. Antes de programar cualquier comando, revisa sus opciones con `--help`.

## 4. Respaldos

- **Automáticos (Windows):** la carpeta `C:\JANOTEC_INTEGRACION\respaldos\automaticos\jano` conserva las últimas 30 copias.
- **Manual:**

  ```bash
  python manage.py respaldar_bd --destino <carpeta>
  ```

  La copia es segura con la plataforma encendida.
- **Restaurar:**
  1. Detén la plataforma.
  2. Copia el `.sqlite3` elegido sobre `db.sqlite3`.
  3. Inicia la plataforma.
- **Regla:** respalda siempre antes de migrar o de importar datos.

## 5. Actualizar la plataforma

El código se cambia **solo en el equipo local**; el servidor únicamente lo baja de GitHub:

1. **Local:** hacer el cambio y probarlo (`python manage.py test` y una revisión en el navegador).
2. **Local:** commit y `git push` a la rama `main`.
3. **Servidor:** actualizar con el script `actualizar.sh` o con la publicación automática de Plesk (abajo).
4. Revisar el ingreso, el tablero, una lista de equipos y un informe en PDF.

En el servidor solo se editan a mano el `.env` y `passenger_wsgi.py`. Los datos (`db.sqlite3`, `media/`) viven en el servidor y **no** viajan por GitHub.

### Con el script (por SSH)

```bash
cd /ruta/de/la/plataforma && ./actualizar.sh
```

En orden: respalda la base en `respaldos/antes_de_actualizar/` (conserva 30 copias), baja los cambios con `git pull --ff-only`, instala dependencias si el sitio tiene entorno virtual, aplica las migraciones, ejecuta `collectstatic` y `check`, y reinicia Passenger (`tmp/restart.txt`). Si un paso falla, se detiene ahí.

- Si encuentra cambios hechos a mano en el servidor, `git pull` se detiene para no pisarlos: revísalos con `git status`.
- Para usar un Python distinto: `PY=/ruta/python ./actualizar.sh`.
- La primera vez puede hacer falta darle permiso: `chmod +x actualizar.sh` (o correrlo con `bash actualizar.sh`).

### Publicación automática (Plesk Git)

Igual que en la plataforma de tickets, cada `git push` a `main` puede publicarse solo:

1. En Plesk › **Git**, agrega el repositorio `GestionSistemas` apuntando a la carpeta de la aplicación, rama `main`, modo de implementación **automático**.
2. En GitHub › *Settings › Webhooks*, pega el *webhook* que muestra Plesk (evento *push*).
3. En **Acciones de implementación adicionales**, con el Python del sitio:

   ```bash
   PY=<python 3.10 que ejecuta Django>
   mkdir -p .runtime/vendor
   "$PY" -m pip install --target .runtime/vendor "pysqlite3-binary==0.5.4"
   $PY manage.py respaldar_bd --destino respaldos/antes_de_actualizar --conservar 30
   $PY manage.py migrate --noinput
   $PY manage.py collectstatic --noinput -v 0
   mkdir -p tmp && touch tmp/restart.txt
   ```

Si un cambio no aparece, en Plesk › Git › **Extraer actualizaciones** se baja a mano; `actualizar.sh` queda como respaldo.

La instalación en `.runtime/vendor` debe ejecutarse **antes del primer comando
Django** de cada despliegue. Si Plesk solo deja ejecutar `touch .../deploy.pending`
y un proceso propio hace las migraciones, ese proceso también debe instalar
`pysqlite3-binary` antes de `check`, `makemigrations` o `migrate` (o debe llamar
a `actualizar.sh`). No ejecutes los comandos Django con el Python 3.6.8 que
aparece en una configuración que no encuentra `passenger_wsgi.py`: esta versión
del proyecto usa Django 5.2 y requiere Python 3.10 o posterior.

**Cuidado con las migraciones:** con la publicación automática se aplican apenas llega el `push`. Antes de subir una migración que cambie o borre datos, revísala en local con una copia de la base del servidor.

## 6. Cuentas de usuario

- **Personal de TIC y Talento humano:** las crea un superusuario en **Control › Accesos a la plataforma**, con su rol (ver la tabla de roles en ARQUITECTURA.md, sección 5).
- **Funcionarios (portal Mi soporte):** su usuario es la cédula. Primero revisa qué cuentas se crearían:

  ```bash
  python manage.py crear_cuentas_solicitantes
  ```

  Después créalas y envía los correos con `--enviar`. Para probar con una sola persona, agrega `--cedula <número>`.
- **Contraseña olvidada:** cada persona la recupera con "¿Primer ingreso u olvidaste tu contraseña?" en la pantalla de ingreso. El enlace llega a su correo y vale 7 días.

## 7. Bitácoras y solución de problemas

| Problema | Dónde mirar / qué hacer |
|---|---|
| La plataforma no abre (Windows) | `operacion\logs\jano-errores.log` y `arranque.log`. Vuelve a ejecutar `iniciar_plataformas.ps1`. |
| No llegan correos | Datos `EMAIL_*` del `.env`. Prueba con `procesar_alertas_mantenimiento` sin `--enviar`, que solo simula. |
| "Tu rol no permite realizar esta acción" | Un superusuario debe darle el rol adecuado en Control › Accesos a la plataforma. |
| Se ve el diseño antiguo o desordenado | Recarga con Ctrl+F5. En Plesk, ejecuta `collectstatic` y reinicia. |
| Error al guardar después de actualizar | Faltan migraciones: ejecuta `python manage.py migrate`, con respaldo previo. |
| Quién cambió un dato | Menú **Auditoría**: filtra por placa, usuario o fecha. |
