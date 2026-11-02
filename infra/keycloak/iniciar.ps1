# Arranca Keycloak (proveedor de identidad, §11) con el reino de NeuroLab.
#
#   powershell -ExecutionPolicy Bypass -File infra\keycloak\iniciar.ps1
#
# Usa la base PostgreSQL `keycloak` que crea infra\postgres\crear_base.ps1 y escucha en
# http://localhost:8180 (consola de administración: /admin, usuario `admin`; la clave está
# en .env como KEYCLOAK_ADMIN_PASSWORD). La primera vez importa infra\keycloak\neurolab-realm.json.
#
# -BaseLocal: base de archivos propia de Keycloak, sin PostgreSQL (solo para pruebas rápidas).

param(
    [string]$Keycloak = "",
    [int]$Puerto = 8180,
    [switch]$BaseLocal
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $Keycloak) { $Keycloak = Join-Path (Split-Path $root -Parent) "herramientas\keycloak-26.8.1" }
if (-not (Test-Path "$Keycloak\bin\kc.bat")) { throw "No se encontró Keycloak en '$Keycloak'. Indica la ruta con -Keycloak." }

function Read-Env([string]$Name) {
    # Una variable de entorno ya definida prevalece sobre .env (igual que en la API).
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { return $fromEnv }
    $file = Join-Path $root ".env"
    if (-not (Test-Path $file)) { return $null }
    $line = Get-Content $file | Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
    if ($line) { return $line.Substring($Name.Length + 1).Trim() }
    return $null
}

if (-not $env:JAVA_HOME) {
    $jdk = Get-ChildItem "C:\Program Files\Java" -Directory -Filter "jdk-*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($jdk) { $env:JAVA_HOME = $jdk.FullName }
}

# El reino se importa al arrancar si aún no existe (las ejecuciones siguientes lo conservan).
$import = Join-Path $Keycloak "data\import"
New-Item -ItemType Directory -Force $import | Out-Null
Copy-Item (Join-Path $PSScriptRoot "neurolab-realm.json") $import -Force

$adminPassword = Read-Env "KEYCLOAK_ADMIN_PASSWORD"
if (-not $adminPassword) { throw "Falta KEYCLOAK_ADMIN_PASSWORD en .env: ejecuta antes infra\postgres\crear_base.ps1." }
$env:KC_BOOTSTRAP_ADMIN_USERNAME = "admin"
$env:KC_BOOTSTRAP_ADMIN_PASSWORD = $adminPassword

$arguments = @("start-dev", "--http-port=$Puerto", "--import-realm", "--hostname=http://localhost:$Puerto")
if (-not $BaseLocal) {
    $dbPassword = Read-Env "KEYCLOAK_DB_PASSWORD"
    if (-not $dbPassword) { throw "Falta KEYCLOAK_DB_PASSWORD en .env: ejecuta antes infra\postgres\crear_base.ps1." }
    $env:KC_DB = "postgres"
    $env:KC_DB_URL = "jdbc:postgresql://localhost:5432/keycloak"
    $env:KC_DB_USERNAME = "keycloak"
    $env:KC_DB_PASSWORD = $dbPassword
}

Write-Host "Keycloak en http://localhost:$Puerto (reino 'neurolab'). Ctrl+C para detenerlo."
try {
    & "$Keycloak\bin\kc.bat" @arguments
} finally {
    Remove-Item Env:KC_DB_PASSWORD, Env:KC_BOOTSTRAP_ADMIN_PASSWORD -ErrorAction SilentlyContinue
}
