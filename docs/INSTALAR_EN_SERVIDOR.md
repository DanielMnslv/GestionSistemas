# JANO Inventario: instalar en el servidor Ubuntu con Plesk

Se instala desde dos partes:

- **El código**: este repositorio de GitHub.
- **La base de datos** (`db.sqlite3`) con todos los datos. **No está en GitHub** porque trae datos personales (nombres, cédulas, correos). Llega aparte, por un medio privado, en el archivo `JANO_base_datos_*.zip`.

Con las dos partes, el sitio queda igual al equipo local.

## Requisitos

- Python 3.12 (también sirve 3.10 o superior).
- La aplicación Python de Plesk (Phusion Passenger), la misma que usa hoy `gestionsistemas.seguridadjano.com`.
- `git` en el servidor. Si no está, se puede descargar el repositorio como ZIP desde GitHub (botón **Code > Download ZIP**).

## 1. Respaldo de lo que hay hoy en el servidor

Copia aparte la carpeta actual de la aplicación completa. Debe incluir:

- `db.sqlite3`;
- `.env`;
- `passenger_wsgi.py`.

Si algo sale mal, se vuelve a poner esa carpeta.

## 2. Traer el código

Por SSH, en la carpeta que contiene la aplicación:

```bash
git clone <URL-del-repositorio> jano_nuevo
```

Si el repositorio es privado, GitHub pide usuario y un *token* de acceso. El token se crea en **GitHub > Settings > Developer settings > Personal access tokens**.

Luego copia el contenido de `jano_nuevo/` **encima** de la carpeta de la aplicación. **Conserva** del servidor:

- `passenger_wsgi.py`;
- el entorno virtual (`venv` o `.venv`).

Más adelante, para traer actualizaciones basta con `git pull`. Para eso, la carpeta de la aplicación debe ser el propio clon.

## 3. Poner la base de datos

1. Descomprime `JANO_base_datos_*.zip`.
2. Pon su `db.sqlite3` en la carpeta de la aplicación. **Reemplaza** el del servidor.

## 4. Configuración (`.env`)

1. Usa `docs/env.servidor.ejemplo` como guía y revisa el `.env` actual del servidor.
2. Agrega lo que falte, sobre todo:
   - `DJANGO_SITIO_URL` y `DJANGO_SITIO_URL_PUBLICO`;
   - los datos del correo;
   - `DJANGO_DB_PATH`, si la base no queda en la carpeta de la aplicación.
3. No pongas `DJANGO_HOSTS_PUBLICOS`.

## 5. Instalar y preparar

En la carpeta de la aplicación, con el entorno virtual activo:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
mkdir -p media
chmod -R u+rw media db.sqlite3
```

- `migrate` debe decir que no hay migraciones pendientes, porque la base ya viene al día.
- El usuario del sitio en Plesk debe poder escribir en `db.sqlite3`, en la carpeta que lo contiene y en `media/`.

## 6. Reiniciar

Usa una de estas dos formas:

- **Plesk > Sitios web > Python > Reiniciar aplicación**.
- Por SSH: `touch tmp/restart.txt`.

## 7. Revisar

1. Abre `https://gestionsistemas.seguridadjano.com/login/`. Debe salir "¿Primer ingreso u olvidaste tu contraseña?".
2. Entra con un usuario de TIC. Debe verse el menú **Solicitudes**.
3. Revisa que abran estas páginas:
   - `/inventario/solicitudes/agenda/`;
   - `/mi-soporte/`;
   - un informe en PDF.

## 8. Cuentas para los funcionarios

Haz esto solo cuando todo lo anterior funcione. El usuario de cada funcionario es su cédula, y le llega por correo un enlace para crear su contraseña.

```bash
python manage.py crear_cuentas_solicitantes                           # solo muestra qué haría
python manage.py crear_cuentas_solicitantes --cedula 1234567890 --enviar  # prueba con una persona
python manage.py crear_cuentas_solicitantes --enviar                  # a todos
```

## Importante

- Después de esto, **el trabajo diario se hace solo en el servidor**. Si también se registra en el equipo local, las dos bases se separan.
- Los registros que existían solo en el servidor se reemplazan por los del equipo local, incluidos los tickets antiguos. Quedan en el respaldo del paso 1.
- Nunca subas `db.sqlite3` ni `.env` a GitHub. El `.gitignore` ya los excluye.
