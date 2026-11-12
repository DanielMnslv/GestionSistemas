@echo off
setlocal
cd /d "%~dp0"

REM Entorno local aislado: NO usa .env ni credenciales de integracion.
set DJANGO_DEBUG=True
set DJANGO_HTTPS=False
set DJANGO_DB_PATH=%CD%\db_trabajo_local.sqlite3
set DJANGO_SECRET_KEY=jano-local-preview-only-change-before-any-publication
set DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
set DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8080,http://localhost:8080
set DJANGO_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
set INTEGRACION_GESTION_TIC_URL=
set INTEGRACION_GESTION_TIC_SECRET=
set DJANGO_ENV_FILE=

set PYTHON=
if exist "%CD%\.venv_demo\Scripts\python.exe" set PYTHON="%CD%\.venv_demo\Scripts\python.exe"
if not defined PYTHON if exist "%CD%\..\jano_inventario\.venv\Scripts\python.exe" set PYTHON="%CD%\..\jano_inventario\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%CD%\..\..\jano_inventario\.venv\Scripts\python.exe" set PYTHON="%CD%\..\..\jano_inventario\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%CD%\.venv\Scripts\python.exe" set PYTHON="%CD%\.venv\Scripts\python.exe"
if not defined PYTHON (
  where py >nul 2>nul
  if errorlevel 1 (
    echo No encuentro Python. Instala Python 3.12 o configura el entorno virtual.
    pause
    exit /b 1
  )
  set PYTHON=py -3.12
)

%PYTHON% -c "import django, rest_framework, dotenv, whitenoise" >nul 2>nul
if errorlevel 1 (
  echo Faltan dependencias. Se instalaran en un entorno aislado .venv_demo.
  if not exist "%CD%\.venv_demo\Scripts\python.exe" (
    %PYTHON% -m venv .venv_demo
    if errorlevel 1 goto error
  )
  set PYTHON="%CD%\.venv_demo\Scripts\python.exe"
  %PYTHON% -m pip install --upgrade pip
  %PYTHON% -m pip install -r requirements.txt
  if errorlevel 1 goto error
)

if not exist "%DJANGO_DB_PATH%" (
  if not exist "%CD%\db_origen_copia_inicial.sqlite3" (
    echo No se encuentra la copia inicial de la base de datos.
    goto error
  )
  echo Creando una copia de trabajo. La copia inicial permanecera intacta.
  copy /y "%CD%\db_origen_copia_inicial.sqlite3" "%DJANGO_DB_PATH%" >nul
  if errorlevel 1 goto error
)

echo.
echo JANO INVENTARIO - VISTA LOCAL CON DATOS REALES COPIADOS
echo URL: http://127.0.0.1:8080
echo Inicia sesion con uno de los usuarios existentes de la copia.
echo Integracion externa y envio de correo desactivados.
echo La base original no se modifica; se usa db_trabajo_local.sqlite3.
echo Para detener el servidor presiona CTRL+C.
echo.
%PYTHON% -m waitress --listen=127.0.0.1:8080 config.wsgi:application
pause
exit /b 0

:error
echo No se pudo preparar el entorno. La base inicial no se modifico.
pause
exit /b 1
