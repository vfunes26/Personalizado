@echo off
setlocal EnableExtensions
title Cita Extranjeria Helper - Compilacion local Personalizada
set "RAIZ=%SystemDrive%\CitaHelper"
set "CONTROL="
if not exist "%RAIZ%\Proyecto\" (
  echo [ERROR] No existe %RAIZ%\Proyecto
  echo Se necesita la carpeta CitaHelper preparada en la raiz del disco.
  goto :error
)
if exist "%~dp0scripts\compilar_portable.ps1" (
  set "CONTROL=%~dp0scripts\compilar_portable.ps1"
)
if not defined CONTROL if exist "%RAIZ%\Proyecto\Personalizado-main\scripts\compilar_portable.ps1" (
  set "CONTROL=%RAIZ%\Proyecto\Personalizado-main\scripts\compilar_portable.ps1"
)
if not defined CONTROL (
  for /d %%D in ("%RAIZ%\Proyecto\*") do (
    if not defined CONTROL if exist "%%~fD\scripts\compilar_portable.ps1" (
      set "CONTROL=%%~fD\scripts\compilar_portable.ps1"
    )
  )
)
if not defined CONTROL (
  echo [ERROR] Falta scripts\compilar_portable.ps1 en CitaHelper\Proyecto.
  echo Primero extrae en CitaHelper\Proyecto el ZIP actualizado de Personalizado.
  goto :error
)
echo.
echo Cita Extranjeria Helper - Personalizado
echo Se compilara la ultima fuente de GitHub sin descargar Camoufox ni FPGen.
echo El portable original del Escritorio no se modifica.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CONTROL%" %*
set "RESULTADO=%ERRORLEVEL%"
echo.
if not "%RESULTADO%"=="0" (
  echo [ERROR] La compilacion no finalizo. Codigo: %RESULTADO%
  goto :error
)
echo [OK] El portable nuevo se encuentra en:
echo %RAIZ%\Compilaciones\Cita Extranjeria Helper - Personalizado
if not defined CEH_NO_PAUSE pause
exit /b 0
:error
if not defined CEH_NO_PAUSE pause
exit /b 1
