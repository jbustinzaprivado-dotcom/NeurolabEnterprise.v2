@echo off
REM Demostracion publica temporal (tunel de Cloudflare). Doble clic para abrirla.
REM Antes, cierra las ventanas de run.bat. Para terminar, usa demo-detener.bat.
cd /d "%~dp0"
echo ============================================
echo   NeuroLab - demostracion publica
echo ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "infra\demo\exponer.ps1"
if errorlevel 1 (
    echo.
    echo [ERROR] La demostracion no pudo arrancar. Revisa el mensaje anterior.
)
echo.
echo Deja abiertas las ventanas de Keycloak, API, worker y web mientras dure la demo.
pause
