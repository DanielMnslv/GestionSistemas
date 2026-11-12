# Publicar la plataforma en un servidor

Para usar la plataforma desde el celular en campo debe estar en un servidor
con HTTPS. Estos pasos sirven para cualquier servidor (de la empresa o un
hosting); solo cambia el servidor web que va delante.

## Opción actual: en este computador (http://localhost:8080)

La plataforma corre con Waitress en este equipo y solo se abre desde él
(el celular necesita publicarla en la red o en internet; ver las
secciones siguientes).

- Configuración: `.env.produccion` (no se sube a git): `DJANGO_DEBUG=False`,
  clave secreta propia, `DJANGO_HTTPS=False` porque se sirve por HTTP local.
- Iniciar: `iniciar_plataforma.bat` (aplica migraciones, recolecta los
  estáticos y arranca Waitress en el puerto 8080). Registro en
  `registro_plataforma.log`.
- Tareas diarias: `tareas_diarias.bat` (respaldo, sincronización con el
  Sheet, alertas de mantenimiento y antivirus).
  Registro en `registro_tareas.log`.
- En el Programador de tareas de Windows: `iniciar_plataforma.bat` al
  iniciar sesión y `tareas_diarias.bat` una vez al día.

Para abrirla a otros computadores de la oficina: cambia `--listen` a
`0.0.0.0:8080` en `iniciar_plataforma.bat`, agrega la IP del equipo a
`DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS` y permite el puerto
8080 en el firewall de Windows.

## 1. Preparar el proyecto

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # en Linux: .venv/bin/python
```

Copia `.env.example` como `.env` y completa al menos:

- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY` (el comando para generarla está en el archivo)
- `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS` con el dominio
- el correo (`EMAIL_*`) para las alertas

Luego:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```

`check --deploy` solo debe advertir sobre `SECURE_HSTS_SECONDS`; súbelo
cuando el HTTPS lleve unos días estable.

## 2. Servidor de aplicación y servidor web

Django no debe servirse con `runserver` en producción:

- **Windows:** `waitress-serve --listen=127.0.0.1:8000 config.wsgi:application`
  (instalar `waitress`), detrás de IIS o Caddy.
- **Linux:** `gunicorn config.wsgi:application --bind 127.0.0.1:8000`
  (instalar `gunicorn`), detrás de Nginx o Caddy.

El servidor web termina el HTTPS, envía la cabecera
`X-Forwarded-Proto: https` y sirve la carpeta `staticfiles/` en `/static/`.

## 3. Tareas programadas

| Tarea | Comando | Frecuencia |
|---|---|---|
| Respaldo de la base | `python manage.py respaldar_bd --conservar 30` | Diaria |
| Alertas de mantenimiento | `python manage.py procesar_alertas_mantenimiento --enviar` | Diaria |
| Antivirus por vencer | `python manage.py procesar_alertas_antivirus --enviar` | Diaria |
| Sincronizar el Sheet (mientras se use) | `python manage.py sincronizar_sheet --usuario admin --confirmar` | Diaria |

Copia la carpeta de respaldos (`JANO_RESPALDOS_DIR`) fuera del servidor
con regularidad.

## 4. Usuarios y roles

Crea los usuarios desde *Usuarios* (solo el superusuario):

| Rol | Puede |
|---|---|
| Encargado de inventario | Registrar, editar y dar de baja radios; entregas y devoluciones; programar mantenimientos |
| Técnico de mantenimiento | Registrar intervenciones; programar, completar y cancelar mantenimientos |
| Consulta | Ver la información |

## 5. Dejar de usar el Google Sheet

Cuando la plataforma esté publicada y el personal sepa usarla:

1. Ejecuta una última sincronización:
   `python manage.py sincronizar_sheet --usuario admin --confirmar`.
2. En Google Forms, desactiva "Aceptar respuestas" en todos los
   formularios (radios, mantenimiento, computadores, impresoras,
   GPS, antivirus y política).
3. Comparte el Sheet solo como lector, para consulta histórica.
4. Quita la tarea programada de sincronización.

Desde ese momento todo se registra en la plataforma:

| Antes (Sheet / formulario) | Ahora (plataforma) |
|---|---|
| BASEDATOS-RADIOS, RESPUESTA-RADIOS | Radios y Entregas de radios |
| BASEDATOS-COMPUTADOR, _IMP, _GPS, _ALARMAS | Equipos de TI |
| ASIG-COMPUTADOR, resp_imp | Entregar a un funcionario (ficha del equipo) |
| RPTAGPS | Cambio de vehículo o línea (ficha del GPS) |
| BD MANTENIMIENTO, T.MANT, MANTENIMIENTO PREVENTIVO | Intervenciones y mantenimientos programados |
| VERIFICACION POLITICA | Política de seguridad |
| RESPANTIV | Renovar antivirus (ficha del computador) |
| ACTIVOS_MAESTRO | Estado de mantenimientos |
| CLIENTES_PUESTOS | Clientes y puestos |
| HOJA DE VIDA … | Hoja de vida (ficha del equipo) |
