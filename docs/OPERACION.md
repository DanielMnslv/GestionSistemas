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

1. Respalda la base de datos.
2. Trae el código nuevo con `git pull`.
3. Instala las dependencias con `pip install -r requirements.txt`.
4. Aplica las migraciones con `python manage.py migrate`. **No se aplican solas.**
5. En Plesk, ejecuta `python manage.py collectstatic --noinput`. En Windows lo hace el script de inicio.
6. Reinicia la plataforma.
7. Revisa el ingreso, el tablero, una lista de equipos y un informe en PDF.

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
