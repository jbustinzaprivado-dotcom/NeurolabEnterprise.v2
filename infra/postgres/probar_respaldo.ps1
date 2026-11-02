# Prueba de restauración (§11: "copias de seguridad probadas").
#
#   powershell -ExecutionPolicy Bypass -File infra\postgres\probar_respaldo.ps1
#
# Hace un respaldo nuevo, lo restaura en la base de pruebas (neurolab_test, que las
# pruebas automáticas recrean en cada ejecución) y compara las filas tabla por tabla.

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_conexion.ps1")

& (Join-Path $PSScriptRoot "respaldo.ps1")
$latest = Get-ChildItem (Join-Path $Script:Root "data\backups") -Directory | Sort-Object Name -Descending | Select-Object -First 1
$manifest = Get-Content (Join-Path $latest.FullName "manifiesto.json") -Raw -Encoding utf8 | ConvertFrom-Json

$test = Get-NeuroLabConnection "NEUROLAB_TEST_DATABASE_URL"
Invoke-PgTool "psql" $test @("-d", $test.Database, "-q", "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
& (Join-Path $PSScriptRoot "restaurar.ps1") -Respaldo $latest.Name -Base $test.Database -SinArchivos

$restored = Get-TableCounts $test $test.Database
$fallos = 0
foreach ($entry in $manifest.tablas.PSObject.Properties) {
    $ok = $restored[$entry.Name] -eq [int]$entry.Value
    if (-not $ok) { $fallos++ }
    Write-Host ("{0,-20} origen={1,6} restaurado={2,6} {3}" -f $entry.Name, $entry.Value, $restored[$entry.Name], ($(if ($ok) { "OK" } else { "DIFERENTE" })))
}
if ($fallos -gt 0) { throw "La prueba de restauración falló en $fallos tablas." }
Write-Host "Prueba de restauración superada: $($latest.Name) se restaura completo."
