@echo off
REM Detiene los tuneles de la demostracion publica.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "infra\demo\exponer.ps1" -Detener
echo.
echo Cierra tambien las ventanas de Keycloak, API, worker y web que abrio la demo.
echo Para volver al modo local, ejecuta run.bat.
pause
