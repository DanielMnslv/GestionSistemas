$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        Write-Error "No se encontró Python. Activa el entorno virtual del proyecto."
        exit 1
    }
    $python = $pythonCommand.Source
}

function Invoke-ValidationStep {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Write-Host "`n=== $Title ===" -ForegroundColor Cyan
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Falló: $Title. No se debe publicar este cambio."
        exit $LASTEXITCODE
    }
}

Invoke-ValidationStep -Title "Comprobación de Django" -Arguments @("manage.py", "check")
Invoke-ValidationStep -Title "Migraciones pendientes de generar" -Arguments @("manage.py", "makemigrations", "--check", "--dry-run")
Invoke-ValidationStep -Title "Suite completa de pruebas" -Arguments @("manage.py", "test", "--verbosity", "1")

Write-Host "`n=== Revisión de espacios y conflictos en Git ===" -ForegroundColor Cyan
git diff --check
if ($LASTEXITCODE -ne 0) {
    Write-Error "git diff --check encontró errores. No se debe publicar este cambio."
    exit $LASTEXITCODE
}

Write-Host "`nValidaciones locales aprobadas. Ya puedes subir los cambios." -ForegroundColor Green
exit 0
