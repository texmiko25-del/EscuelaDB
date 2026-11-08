$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

& "$root\.venv\Scripts\python.exe" manage.py enviar_reporte_sistema
if ($LASTEXITCODE -ne 0) {
    throw "La ejecución del reporte diario falló con exit code $LASTEXITCODE."
}
