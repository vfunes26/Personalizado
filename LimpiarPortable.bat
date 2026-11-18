@echo off
setlocal EnableExtensions
set "RAIZ=%SystemDrive%\CitaHelper"
if not exist "%RAIZ%\" (
  echo [ERROR] No existe %RAIZ%
  pause
  exit /b 1
)
rem Si se ejecuta desde el ZIP extraido, instalar los BAT/PS1 actualizados
rem SIN volver a compilar ni descargar el navegador.
if exist "%~dp0scripts\limpiar_portable.ps1" (
  copy /Y "%~dp0scripts\limpiar_portable.ps1" "%RAIZ%\limpiar_portable.ps1" >nul
  if errorlevel 1 goto :error
  if exist "%~dp0scripts\compilar_portable.ps1" (
    copy /Y "%~dp0scripts\compilar_portable.ps1" "%RAIZ%\compilar_portable.ps1" >nul
    if errorlevel 1 goto :error
  )
  if exist "%~dp0CompilarPortable.bat" (
    copy /Y "%~dp0CompilarPortable.bat" "%RAIZ%\CompilarPortable.bat" >nul
    if errorlevel 1 goto :error
  )
  copy /Y "%~f0" "%RAIZ%\LimpiarPortable.bat" >nul
  if errorlevel 1 goto :error
)
if not exist "%RAIZ%\CompilarPortable.bat" goto :error
if not exist "%RAIZ%\limpiar_portable.ps1" goto :error
echo.
echo LIMPIEZA DESPUES DE HABER PROBADO EL PORTABLE
echo No se ejecutara otra compilacion. Los datos privados estan protegidos.
call "%RAIZ%\CompilarPortable.bat" /limpiar
exit /b %ERRORLEVEL%
:error
echo [ERROR] No fue posible instalar el limpiador del ZIP en %RAIZ%.
pause
exit /b 1
