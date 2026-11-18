@echo off
setlocal EnableExtensions
set "RAIZ=%SystemDrive%\CitaHelper"
if not exist "%RAIZ%\CompilarPortable.bat" (
  echo [ERROR] Falta CompilarPortable.bat en %RAIZ%
  pause
  exit /b 1
)
echo.
echo LIMPIEZA DESPUES DE PROBAR EL PORTABLE
echo El entorno Python, las caches y los datos privados no se eliminan.
call "%RAIZ%\CompilarPortable.bat" /limpiar
exit /b %ERRORLEVEL%
