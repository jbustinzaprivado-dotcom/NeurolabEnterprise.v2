# Restaura un respaldo de NeuroLab (§11).
#
#   powershell -ExecutionPolicy Bypass -File infra\postgres\restaurar.ps1 -Respaldo 20261102-103000 [-Base neurolab] [-SinArchivos] [-Keycloak]
#
# Detén la API y el worker antes de restaurar sobre la base de trabajo (y Keycloak si usas
# -Keycloak, que restaura también sus cuentas). Se verifica el checksum de cada archivo del
# respaldo antes de tocar nada.

param(
    [Parameter(Mandatory = $true)][string]$Respaldo,
    [string]$Base = "",
    [switch]$SinArchivos,
    [switch]$Keycloak
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

if ($Keycloak) {
    $kc = Get-KeycloakConnection
    $dump = Join-Path $source "keycloak.dump"
    if (-not $kc) { throw "Falta KEYCLOAK_DB_PASSWORD en .env." }
    if (-not (Test-Path $dump)) { throw "Este respaldo no incluye la base de Keycloak." }
    Write-Host "Restaurando las cuentas de Keycloak..."
    Invoke-PgTool "pg_restore" $kc @("-d", $kc.Database, "--clean", "--if-exists", "--no-owner", "--single-transaction", $dump)
}

if (-not $SinArchivos) {
    Write-Host "Restaurando datasets y modelos en data\..."
    Expand-Archive (Join-Path $source "archivos.zip") -DestinationPath (Join-Path $Script:Root "data") -Force
}
Write-Host "Restauración completa desde $Respaldo."
