# Demostración pública temporal: publica el sistema local con dos túneles de Cloudflare
# (gratis, sin cuenta) para entrar desde otro dispositivo con HTTPS. No es para producción.
#
#   powershell -ExecutionPolicy Bypass -File infra\demo\exponer.ps1
#   powershell -ExecutionPolicy Bypass -File infra\demo\exponer.ps1 -Detener
#
# Requisitos: cloudflared instalado (winget install --id Cloudflare.cloudflared), la base ya
# creada con crear_base.ps1 y las ventanas de run.bat CERRADAS (este script arranca todo).
#
# Qué hace:
#   1. Abre un túnel para Keycloak (8180) y otro para la web (4173) y lee sus direcciones.
#   2. Arranca Keycloak con la dirección pública y añade la de la web al cliente neurolab-web.
#   3. Arranca la API y el worker con el emisor público y compila la web (vite preview).
# Las direcciones cambian en cada ejecución y dejan de funcionar al cerrar los túneles.

param([switch]$Detener)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$state = Join-Path $env:TEMP "neurolab-demo"
$pidFile = Join-Path $state "tuneles.pid"

function Stop-Tunnels {
    if (Test-Path $pidFile) {
        Get-Content $pidFile | ForEach-Object {
            Stop-Process -Id ([int]$_) -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $pidFile -Force
    }
}

if ($Detener) {
    Stop-Tunnels
    Write-Host "Túneles detenidos. Cierra las ventanas de Keycloak, API, worker y web para terminar."
    exit 0
}

$cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cloudflared) {
    $default = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if (Test-Path $default) { $cloudflared = $default }
}
if (-not $cloudflared) {
    throw "No se encontró cloudflared. Instálalo con: winget install --id Cloudflare.cloudflared (y abre una terminal nueva)."
}

foreach ($port in 8000, 8180, 4173) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "El puerto $port está en uso: cierra antes las ventanas de run.bat (API, worker, Keycloak y web)."
    }
}

function Read-Env([string]$Name) {
    $file = Join-Path $root ".env"
    $line = Get-Content $file | Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
    if ($line) { return $line.Substring($Name.Length + 1).Trim() }
    return $null
}

function Wait-Url([string]$Url, [int]$Seconds, [string]$What) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 | Out-Null
            return
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "$What no respondió en $Seconds s ($Url)."
}

function Start-Tunnel([int]$Port, [string]$Name) {
    $log = Join-Path $state "$Name.log"
    if (Test-Path $log) { Remove-Item $log -Force }
    $process = Start-Process -FilePath $cloudflared -WindowStyle Hidden -PassThru `
        -ArgumentList @("tunnel", "--no-autoupdate", "--url", "http://localhost:$Port") `
        -RedirectStandardError $log
    Add-Content -Path $pidFile -Value $process.Id
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        if (Test-Path $log) {
            $match = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
            if ($match) { return $match.Matches[0].Value }
        }
    }
    throw "El túnel de $Name no entregó una dirección. Revisa $log."
}

New-Item -ItemType Directory -Force $state | Out-Null
Stop-Tunnels

Write-Host "1/5 Abriendo túneles de Cloudflare..."
$kcUrl = Start-Tunnel 8180 "keycloak"
$webUrl = Start-Tunnel 4173 "web"
Write-Host "    Keycloak: $kcUrl"
Write-Host "    Web:      $webUrl"

Write-Host "2/5 Arrancando Keycloak con la dirección pública (tarda ~30 s)..."
Start-Process powershell -WorkingDirectory $root -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "infra\keycloak\iniciar.ps1", "-Publico", $kcUrl
)
Wait-Url "http://localhost:8180/realms/neurolab" 180 "Keycloak"

Write-Host "3/5 Autorizando la dirección de la web en el cliente neurolab-web..."
$admin = Read-Env "KEYCLOAK_ADMIN_PASSWORD"
$token = (Invoke-RestMethod -Method Post -Uri "http://localhost:8180/realms/master/protocol/openid-connect/token" -Body @{
    grant_type = "password"; client_id = "admin-cli"; username = "admin"; password = $admin
}).access_token
$headers = @{ Authorization = "Bearer $token" }
$api = "http://localhost:8180/admin/realms/neurolab/clients"
$client = (Invoke-RestMethod -Uri "$api`?clientId=neurolab-web" -Headers $headers)[0]
# Se quitan túneles de demostraciones anteriores y se añade el actual, más la web local
# (http://localhost:4173) para poder probar también desde esta laptop.
$demoUris = @("$webUrl/*", "http://localhost:4173/*")
$keep = { param($uri) $uri -and $uri -notmatch "trycloudflare\.com" -and $demoUris -notcontains $uri }
$client.redirectUris = @($client.redirectUris | Where-Object { & $keep $_ }) + $demoUris
$logout = @(($client.attributes."post.logout.redirect.uris" -split "##") | Where-Object { & $keep $_ }) + $demoUris
$client.attributes."post.logout.redirect.uris" = ($logout -join "##")
Invoke-RestMethod -Method Put -Uri "$api/$($client.id)" -Headers $headers -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes(($client | ConvertTo-Json -Depth 20))) | Out-Null

Write-Host "4/5 Arrancando la API y el worker..."
$python = Join-Path $root "venv\Scripts\python.exe"
$envLine = "`$env:NEUROLAB_OIDC_ISSUER='$kcUrl/realms/neurolab'; `$env:NEUROLAB_OIDC_INTERNAL_URL='http://localhost:8180/realms/neurolab'; `$env:NEUROLAB_CORS_ORIGINS='$webUrl,http://localhost:5173';"
Start-Process powershell -WorkingDirectory $root -ArgumentList @(
    "-NoProfile", "-NoExit", "-Command", "$envLine & '$python' services\api\app\main.py"
)
Start-Process powershell -WorkingDirectory $root -ArgumentList @(
    "-NoProfile", "-NoExit", "-Command", "$envLine & '$python' workers\training\main.py"
)
Wait-Url "http://127.0.0.1:8000/api/v1/auth/config" 120 "La API"
$config = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/auth/config"
if (-not $config.authorizationEndpoint.StartsWith($kcUrl)) {
    throw "La API no tomó la dirección pública de Keycloak (devolvió $($config.authorizationEndpoint))."
}

Write-Host "5/5 Compilando y sirviendo la web..."
$web = Join-Path $root "apps\web"
Push-Location $web
try {
    npm run build | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "La compilación de la web falló: ejecuta 'npm run build' en apps\web para ver el error." }
} finally { Pop-Location }
Start-Process powershell -WorkingDirectory $web -ArgumentList @(
    "-NoProfile", "-NoExit", "-Command", "npx vite preview --port 4173 --strictPort"
)
Wait-Url "http://localhost:4173" 60 "La web"

Write-Host ""
Write-Host "Listo. Abre desde cualquier dispositivo:" -ForegroundColor Green
Write-Host "    $webUrl" -ForegroundColor Green
Write-Host "(La dirección cambia en cada demo: las de demos anteriores ya no sirven.)"
Write-Host "Usuarios demo: ana.quispe, sofia.ramirez, rosa.medina, carla.nunez (clave neurolab2026)."
Write-Host "Para terminar: cierra las ventanas abiertas y ejecuta este script con -Detener."
