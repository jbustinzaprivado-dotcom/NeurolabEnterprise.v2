# Crea el usuario y las bases de NeuroLab en el PostgreSQL local (§5) y deja la conexión en .env.
#
#   powershell -ExecutionPolicy Bypass -File infra\postgres\crear_base.ps1
#
# psql pedirá la contraseña del superusuario (postgres). La clave del usuario `neurolab` se
# genera aquí al azar y solo se guarda en .env, que no se sube al repositorio (§11).

param(
    [string]$Psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe",
    [string]$AdminUser = "postgres",
    [string]$DbHost = "localhost",
    [int]$Port = 5432
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$envFile = Join-Path $root ".env"

if ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^NEUROLAB_DATABASE_URL=' -Quiet)) {
    Write-Host ".env ya tiene NEUROLAB_DATABASE_URL; no se modifica nada."
    exit 0
}
if (-not (Test-Path $Psql)) {
    throw "No se encontró psql en '$Psql'. Indica la ruta con -Psql."
}

# Solo letras y dígitos: no necesita escaparse ni en SQL ni en la URL.
$chars = [char[]]"abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
$clave = -join (1..28 | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] })

$sql = @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'neurolab') THEN
    CREATE ROLE neurolab LOGIN PASSWORD '$clave';
  ELSE
    ALTER ROLE neurolab LOGIN PASSWORD '$clave';
  END IF;
END
`$`$;
SELECT 'CREATE DATABASE neurolab OWNER neurolab ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'neurolab')\gexec
SELECT 'CREATE DATABASE neurolab_test OWNER neurolab ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'neurolab_test')\gexec
"@

Write-Host "Conectando a PostgreSQL como '$AdminUser' en ${DbHost}:$Port..."
$sql | & $Psql -U $AdminUser -h $DbHost -p $Port -d postgres -v ON_ERROR_STOP=1 -q
if ($LASTEXITCODE -ne 0) {
    throw "psql terminó con error ($LASTEXITCODE). No se modificó .env."
}

$lines = @(
    "",
    "# PostgreSQL local (generado por infra/postgres/crear_base.ps1)",
    "NEUROLAB_DATABASE_URL=postgresql+psycopg2://neurolab:$clave@${DbHost}:$Port/neurolab",
    "NEUROLAB_TEST_DATABASE_URL=postgresql+psycopg2://neurolab:$clave@${DbHost}:$Port/neurolab_test"
)
Add-Content -Path $envFile -Value $lines -Encoding utf8
Write-Host "Listo: bases 'neurolab' y 'neurolab_test' creadas y conexión guardada en .env."
Write-Host "Al arrancar, la API aplica las migraciones y carga los datos demo."
