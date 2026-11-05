# Utilidades comunes de los scripts de respaldo: lee la conexión de .env sin mostrar la clave.

$Script:Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Script:PgBin = "C:\Program Files\PostgreSQL\18\bin"

function Get-NeuroLabConnection([string]$Variable = "NEUROLAB_DATABASE_URL") {
    $envFile = Join-Path $Script:Root ".env"
    if (-not (Test-Path $envFile)) { throw "No existe .env. Ejecuta antes infra\postgres\crear_base.ps1." }
    $line = Get-Content $envFile | Where-Object { $_ -match "^$Variable=" } | Select-Object -First 1
    if (-not $line) { throw "$Variable no está en .env." }
    $url = $line.Substring($Variable.Length + 1).Trim()
    $pattern = '^postgresql(\+\w+)?://(?<user>[^:]+):(?<pass>[^@]+)@(?<host>[^:/]+):(?<port>\d+)/(?<db>[^?]+)'
    if ($url -notmatch $pattern) { throw "$Variable no tiene el formato postgresql://usuario:clave@host:puerto/base." }
    return [pscustomobject]@{ User = $Matches.user; Password = $Matches.pass; Host = $Matches.host; Port = $Matches.port; Database = $Matches.db }
}

# Base de Keycloak (§11): cuentas, contraseñas y sesiones del proveedor de identidad. Usa el
# servidor de NeuroLab con el usuario `keycloak`; la clave es KEYCLOAK_DB_PASSWORD de .env.
function Get-KeycloakConnection {
    $envFile = Join-Path $Script:Root ".env"
    $line = Get-Content $envFile | Where-Object { $_ -match "^KEYCLOAK_DB_PASSWORD=" } | Select-Object -First 1
    if (-not $line) { return $null }
    $neurolab = Get-NeuroLabConnection
    return [pscustomobject]@{
        User = "keycloak"; Password = $line.Substring("KEYCLOAK_DB_PASSWORD=".Length).Trim()
        Host = $neurolab.Host; Port = $neurolab.Port; Database = "keycloak"
    }
}

function Invoke-PgTool([string]$Tool, [pscustomobject]$Conn, [string[]]$Arguments) {
    $exe = Join-Path $Script:PgBin "$Tool.exe"
    if (-not (Test-Path $exe)) { throw "No se encontró $exe." }
    # La clave viaja solo como variable de entorno del proceso hijo, nunca en la línea de comandos.
    $env:PGPASSWORD = $Conn.Password
    try {
        & $exe -h $Conn.Host -p $Conn.Port -U $Conn.User @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$Tool terminó con error ($LASTEXITCODE)." }
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Get-TableCounts([pscustomobject]$Conn, [string]$Database) {
    # Se cuentan las filas de verdad: las estadísticas de pg_stat pueden ir atrasadas.
    $tables = Invoke-PgTool "psql" $Conn @("-d", $Database, "-At", "-c",
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version' ORDER BY tablename")
    $counts = [ordered]@{}
    foreach ($table in $tables) {
        $counts[$table] = [int](Invoke-PgTool "psql" $Conn @("-d", $Database, "-At", "-c", "SELECT count(*) FROM `"$table`""))
    }
    return $counts
}
