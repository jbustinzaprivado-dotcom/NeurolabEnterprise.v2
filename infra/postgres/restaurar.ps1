# Restaura un respaldo de NeuroLab (§11).
#
#   powershell -ExecutionPolicy Bypass -File infra\postgres\restaurar.ps1 -Respaldo 20261102-103000 [-Base neurolab] [-SinArchivos]
#
# Detén la API y el worker antes de restaurar sobre la base de trabajo. Se verifica el
# checksum de cada archivo del respaldo antes de tocar nada.

param(
    [Parameter(Mandatory = $true)][string]$Respaldo,
    [string]$Base = "",
    [switch]$SinArchivos
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_conexion.ps1")

$conn = Get-NeuroLabConnection
if (-not $Base) { $Base = $conn.Database }
$source = Join-Path $Script:Root "data\backups\$Respaldo"
$manifest = Get-Content (Join-Path $source "manifiesto.json") -Raw -Encoding utf8 | ConvertFrom-Json

foreach ($entry in $manifest.archivos.PSObject.Properties) {
    $actual = (Get-FileHash (Join-Path $source $entry.Name) -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $entry.Value) { throw "El checksum de $($entry.Name) no coincide: el respaldo está dañado." }
}

Write-Host "Restaurando la base en '$Base'..."
Invoke-PgTool "pg_restore" $conn @("-d", $Base, "--clean", "--if-exists", "--no-owner", "--single-transaction",
    (Join-Path $source "neurolab.dump"))

if (-not $SinArchivos) {
    Write-Host "Restaurando datasets y modelos en data\..."
    Expand-Archive (Join-Path $source "archivos.zip") -DestinationPath (Join-Path $Script:Root "data") -Force
}
Write-Host "Restauración completa desde $Respaldo."
