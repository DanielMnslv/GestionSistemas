# Publicar cambios después de validar

JANO INVENTARIO valida localmente cada publicación. El hook `pre-push` ejecuta
`scripts/validar_local.ps1` y cancela el push si falla una comprobación.

## Preparación local (una sola vez)

Desde la raíz del repositorio, configura los hooks versionados:

```powershell
git config core.hooksPath .githooks
```

La configuración queda en `.git/config` y no se sube a GitHub. El hook y el
script de validación sí forman parte del repositorio.

## Validar manualmente

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\validar_local.ps1
```

El flujo ejecuta, en orden:

1. `manage.py check`.
2. `manage.py makemigrations --check --dry-run` para detectar modelos sin
   migración.
3. La suite completa de `manage.py test`.
4. `git diff --check`.

Si una etapa falla, la validación se detiene y el hook impide el push. Tras
corregir el problema, vuelve a ejecutar el script y luego publica normalmente.

El hook automatiza la validación en este checkout. Cada persona que clone el
repositorio debe ejecutar una vez el comando de preparación local indicado
arriba; Git no versiona `.git/config`.
