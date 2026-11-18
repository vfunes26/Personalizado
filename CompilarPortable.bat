@echo off
setlocal EnableExtensions
title Cita Extranjeria Helper - Portable Personalizado
set "RAIZ=%SystemDrive%\CitaHelper"
set "CONTROL=%RAIZ%\compilar_portable.ps1"
set "LIMPIADOR=%RAIZ%\limpiar_portable.ps1"
if not exist "%RAIZ%\Proyecto\" (
  echo [ERROR] Falta la carpeta %RAIZ%\Proyecto.
  goto :error
)
rem Copiar controladores livianos fuera de la fuente que luego se puede limpiar.
rem Esto permite mover el BAT al Escritorio o dejarlo en CitaHelper.
if exist "%~dp0scripts\compilar_portable.ps1" (
  copy /Y "%~dp0scripts\compilar_portable.ps1" "%CONTROL%" >nul
  if errorlevel 1 goto :error
)
if exist "%~dp0scripts\limpiar_portable.ps1" (
  copy /Y "%~dp0scripts\limpiar_portable.ps1" "%LIMPIADOR%" >nul
  if errorlevel 1 goto :error
  rem El BAT lanzado desde el ZIP deja su propia copia nueva en la raiz.
  copy /Y "%~f0" "%RAIZ%\CompilarPortable.bat" >nul
  if errorlevel 1 goto :error
  if exist "%~dp0LimpiarPortable.bat" (
    copy /Y "%~dp0LimpiarPortable.bat" "%RAIZ%\LimpiarPortable.bat" >nul
    if errorlevel 1 goto :error
  )
)
if /I "%~1"=="/limpiar" goto :limpiar
if /I "%~1"=="-LimpiarDespuesDeProbar" goto :limpiar
if not exist "%CONTROL%" (
  echo [ERROR] Copia CompilarPortable.bat desde el ZIP extraido junto a scripts
  echo o instala compilar_portable.ps1 en %RAIZ%.
  goto :error
)
echo.
echo Cita Extranjeria Helper - Personalizado
echo Compilando codigo descomprimido manualmente. Sin descargas de GitHub.
echo Se conserva Python, Camoufox, FPGen y el portable original del Escritorio.
echo.
if exist "%~dp0app\version.py" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CONTROL%" -Proyecto "%~dp0." %*
) else (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CONTROL%" %*
)
set "RESULTADO=%ERRORLEVEL%"
goto :resultado
:limpiar
if not exist "%LIMPIADOR%" (
  echo [ERROR] Falta %LIMPIADOR%.
  echo Copia limpiar_portable.ps1 desde el ZIP extraido a %RAIZ%.
  goto :error
)
echo LIMPIEZA DESPUES DE PROBAR EL EJECUTABLE WINDOWS.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%LIMPIADOR%"
set "RESULTADO=%ERRORLEVEL%"
goto :resultado
:resultado
echo.
if not "%RESULTADO%"=="0" (
  echo [ERROR] El proceso no finalizo correctamente. Codigo: %RESULTADO%
  goto :error
)
echo [OK] El portable se conserva en:
echo %RAIZ%\Compilaciones\Cita Extranjeria Helper - Personalizado
if not defined CEH_NO_PAUSE pause
exit /b 0
:error
if not defined CEH_NO_PAUSE pause
exit /b 1
