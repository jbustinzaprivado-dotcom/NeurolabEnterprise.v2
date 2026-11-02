# Prepara PostgreSQL local para NeuroLab (§5) y Keycloak (§11), y deja la configuración en .env.
#
#   powershell -ExecutionPolicy Bypass -File infra\postgres\crear_base.ps1
#
# psql pedirá la contraseña del superusuario (postgres). Las claves de los usuarios `neurolab`
# y `keycloak` y la del administrador de Keycloak se generan aquí al azar y solo se guardan
# en .env, que no se sube al repositorio (§11). Si ya están en .env, no se vuelven a crear.

param(
    [string]$Psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe",
    [string]$AdminUser = "postgres",
    [string]$DbHost = "localhost",
    [int]$Port = 5432
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$envFile = Join-Path $root ".env"

function Test-EnvKey([string]$Name) {
    return (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern "^$Name=" -Quiet)
}

$needNeurolab = -not (Test-EnvKey "NEUROLAB_DATABASE_URL")
$needKeycloak = -not (Test-EnvKey "KEYCLOAK_DB_PASSWORD")
if (-not $needNeurolab -and -not $needKeycloak) {
    Write-Host ".env ya tiene la configuración de NeuroLab y Keycloak; no se modifica nada."
    exit 0
}
if (-not (Test-Path $Psql)) {
    throw "No se encontró psql en '$Psql'. Indica la ruta con -Psql."
}

# Solo letras y dígitos: no necesitan escaparse ni en SQL ni en URLs.
$chars = [char[]]"abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
function New-Secret { -join (1..28 | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] }) }

function Role-Sql([string]$Role, [string]$Password) {
    return @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$Role') THEN
    CREATE ROLE $Role LOGIN PASSWORD '$Password';
  ELSE
    ALTER ROLE $Role LOGIN PASSWORD '$Password';
  END IF;
END
`$`$;
"@ + "`n"
}

function Database-Sql([string]$Database, [string]$Owner) {
    return @"
SELECT 'CREATE DATABASE $Database OWNER $Owner ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$Database')\gexec
"@ + "`n"
}

$sql = ""
$lines = @("")
if ($needNeurolab) {
    $clave = New-Secret
    $sql += (Role-Sql "neurolab" $clave) + (Database-Sql "neurolab" "neurolab") + (Database-Sql "neurolab_test" "neurolab")
    $lines += @(
        "# PostgreSQL local (generado por infra/postgres/crear_base.ps1)",
        "NEUROLAB_DATABASE_URL=postgresql+psycopg2://neurolab:$clave@${DbHost}:$Port/neurolab",
        "NEUROLAB_TEST_DATABASE_URL=postgresql+psycopg2://neurolab:$clave@${DbHost}:$Port/neurolab_test"
    )
}
if ($needKeycloak) {
    $claveKeycloak = New-Secret
    $sql += (Role-Sql "keycloak" $claveKeycloak) + (Database-Sql "keycloak" "keycloak")
    $lines += @(
        "# Proveedor de identidad Keycloak (§11; lo arranca infra/keycloak/iniciar.ps1)",
        "KEYCLOAK_DB_PASSWORD=$claveKeycloak",
        "KEYCLOAK_ADMIN_PASSWORD=$(New-Secret)",
        "NEUROLAB_AUTH_PROVIDER=oidc",
        "NEUROLAB_OIDC_ISSUER=http://localhost:8180/realms/neurolab",
        "NEUROLAB_AUTH_DEV_BYPASS=false"
    )
}

Write-Host "Conectando a PostgreSQL como '$AdminUser' en ${DbHost}:$Port..."
$sql | & $Psql -U $AdminUser -h $DbHost -p $Port -d postgres -v ON_ERROR_STOP=1 -q
if ($LASTEXITCODE -ne 0) {
    throw "psql terminó con error ($LASTEXITCODE). No se modificó .env."
}

Add-Content -Path $envFile -Value $lines -Encoding utf8
if ($needNeurolab) { Write-Host "Listo: bases 'neurolab' y 'neurolab_test' creadas." }
if ($needKeycloak) { Write-Host "Listo: base 'keycloak' creada y proveedor de identidad configurado." }
Write-Host "Configuración guardada en .env. Al arrancar, la API aplica las migraciones y carga los datos demo."
