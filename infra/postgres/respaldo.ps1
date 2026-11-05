# Respaldo completo de NeuroLab (§11): base PostgreSQL + datasets y artefactos de modelos.
#
#   powershell -ExecutionPolicy Bypass -File infra\postgres\respaldo.ps1 [-Conservar 7]
#
# Crea data\backups\<fecha>\ con neurolab.dump (pg_dump, formato custom), keycloak.dump
# (cuentas del proveedor de identidad, si .env lo configura), archivos.zip (data\uploads y
# data\models) y manifiesto.json con los checksums SHA-256.

param([int]$Conservar = 7)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_conexion.ps1")

$conn = Get-NeuroLabConnection
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $Script:Root "data\backups\$stamp"
New-Item -ItemType Directory -Force $target | Out-Null

Write-Host "Volcando la base '$($conn.Database)'..."
Invoke-PgTool "pg_dump" $conn @("-d", $conn.Database, "-Fc", "--no-owner", "-f", (Join-Path $target "neurolab.dump"))

$keycloak = Get-KeycloakConnection
if ($keycloak) {
    Write-Host "Volcando la base de Keycloak (cuentas y sesiones)..."
    Invoke-PgTool "pg_dump" $keycloak @("-d", $keycloak.Database, "-Fc", "--no-owner", "-f", (Join-Path $target "keycloak.dump"))
}

Write-Host "Empaquetando datasets y modelos..."
$sources = @("data\uploads", "data\models") | ForEach-Object { Join-Path $Script:Root $_ } | Where-Object { Test-Path $_ }
Compress-Archive -Path $sources -DestinationPath (Join-Path $target "archivos.zip") -CompressionLevel Optimal

$manifest = [ordered]@{
    creado = (Get-Date).ToUniversalTime().ToString("o")
    base = $conn.Database
    tablas = Get-TableCounts $conn $conn.Database
    keycloak = $(if ($keycloak) { Get-TableCounts $keycloak $keycloak.Database } else { $null })
    archivos = [ordered]@{}
}
foreach ($file in Get-ChildItem $target -File) {
    $manifest.archivos[$file.Name] = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLower()
}
$manifest | ConvertTo-Json -Depth 4 | Out-File (Join-Path $target "manifiesto.json") -Encoding utf8

# Retención de respaldos: se conservan los N más recientes.
Get-ChildItem (Join-Path $Script:Root "data\backups") -Directory | Sort-Object Name -Descending |
    Select-Object -Skip $Conservar | Remove-Item -Recurse -Force

Write-Host "Respaldo listo en $target"
