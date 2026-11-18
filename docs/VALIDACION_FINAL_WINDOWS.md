# Validación final del portable personalizado en Windows

Este documento separa la **validación automática de GitHub Actions** de las
**pruebas reales del ejecutable Windows**. Estas últimas necesitan el ordenador
del usuario; no se simulan como si ya hubieran pasado.

## Condiciones previas

- La compilación se realiza únicamente cuando se terminan los 16 ajustes y
  la persona decide ejecutarla.
- No hace falta abrir Visual Studio. Sus componentes instalados pueden ser
  utilizados por PyInstaller sin iniciar la interfaz de Visual Studio.
- Debe existir `C:\CitaHelper\Proyecto\Personalizado-main\.venv` con
  Python 3.13, PySide6, Playwright, Camoufox, FPGen y PyInstaller.
- Camoufox debe estar instalado en
  `%LOCALAPPDATA%\camoufox\camoufox\Cache` y FPGen debe conservar el
  marcador y los hashes válidos. El BAT **no descarga esos archivos**.
- Solo necesita internet para consultar GitHub y descargar el ZIP del código
  fuente del commit más reciente. El resto de la compilación utiliza recursos
  locales. La compilación no debe iniciarse mientras esté en funcionamiento
  otra compilación en `C:\CitaHelper\Compilaciones`.

## Primera obtención de los scripts

La primera vez, descargar el ZIP fuente de
`https://github.com/vfunes26/Personalizado/archive/refs/heads/main.zip`
y extraerlo en una carpeta dentro de `C:\CitaHelper\Proyecto`, por ejemplo
`Personalizado-final`. **No borrar la carpeta `Personalizado-main`** que
contiene `.venv` ni alterar el portable original.

`CompilarPortable.bat` funciona desde cualquier ubicación siempre que esté
junto a su carpeta `scripts` o exista una copia de
`scripts\compilar_portable.ps1` en alguna carpeta del proyecto bajo
`C:\CitaHelper\Proyecto`. El BAT busca allí el controlador; no necesita
copiar el navegador ni las librerías Python.

## Generación y comprobación del resultado

1. Ejecutar `CompilarPortable.bat` con la aplicación antigua cerrada.
2. El controlador consulta el commit más reciente de
   `vfunes26/Personalizado` y descarga solo su código fuente, con reutilización
   del ZIP si ese commit ya está en caché.
3. Valida el modelo FPGen y Camoufox, comprueba la versión del repositorio y
   realiza una compilación **nativa Windows**, sin construir en GitHub Actions.
4. Ejecuta `scripts/verify_bundle.py` con un directorio temporal de datos
   y sin necesitar conexión al portal de Extranjería. Comprueba navegador
   empaquetado, GUI, origen criptográfico de firma y comunicación del trabajador.
5. Genera ZIP portable, verifica SHA-256, extrae a una carpeta temporal y
   comprueba `portable.flag`, ejecutable, navegador y FPGen.
6. Si existe una compilación propia anterior, el BAT exige que esté cerrada;
   valida los datos y los copia, verificando después todos los bytes con SHA-256.
   Rechaza enlaces o SQLite con archivos `-wal`/`-shm` pendientes.
7. Hace el intercambio únicamente al finalizar las verificaciones. La anterior
   se conserva en `C:\CitaHelper\Compilaciones\Respaldos`. Ante un error, no
   sustituye una compilación funcional y procura restaurarla.

Salida principal:
`C:\CitaHelper\Compilaciones\Cita Extranjeria Helper - Personalizado`

ZIP y checksum:
`C:\CitaHelper\Compilaciones\Paquetes`

## Pruebas manuales después de compilar

Con el portable original intacto:

- Abrir el ejecutable nuevo y comprobar que muestra la versión y la interfaz.
- Verificar apertura del navegador Camoufox y ausencia de descargas de FPGen.
- Crear perfiles de prueba con nombre libre o iniciales, y comprobar que la
  creación existente continúa igual.
- Verificar la lista `/perfiles` en el chat privado autorizado, la numeración
  y la respuesta de confirmación a `/borrar N`. Probar **Cancelar** primero y
  comprobar que no elimina nada. Confirmar la eliminación **solo de un perfil
  de prueba** no activo y que no sea el que mantiene conectado Telegram.
- Comprobar la gestión de perfiles desde Windows, sin afectar trabajadores
  activos. Realizar una prueba de inicio/detención en el entorno adecuado.
- Configurar Gmail con una contraseña de aplicación almacenada en el sistema y
  comprobar un correo de prueba. Verificar el aviso cuando se elimina el perfil
  ficticio.
- Exportar un respaldo cifrado desde el portable original, y restaurarlo desde
  el nuevo usando la interfaz **Importar respaldo**. Requiere confirmación
  explícita para sustituir datos existentes. Las claves nativas de Telegram y
  Gmail deben introducirse de nuevo después de la restauración: no están en
  el archivo cifrado.
- Comprobar integridad de perfiles, trabajadores, proxies, presupuestos y
  estadísticas. No borrar perfiles reales durante las pruebas.

La importación de los datos del portable original **no es automática**: se
requiere consentimiento y contraseña. El BAT conserva datos de compilaciones
anteriores en `Compilaciones`, pero jamás copia o elimina automáticamente los
datos del portable del Escritorio.

## Criterios para declarar finalizado el proyecto

- GitHub Actions `Tests` correspondiente a los ajustes 15–16 aprobado.
- BAT compilado y verificado en el Windows del usuario.
- Inicio de la nueva interfaz y navegador comprobados manualmente.
- Respaldo/restauración, Telegram/Gmail y trabajadores comprobados manualmente.
- Portable anterior conservado hasta que se compruebe la nueva versión.


## Corrección aplicada tras primera compilación en Windows

El primer intento de compilación de la versión `0.3.5` produjo un error
`FileNotFoundError` durante `PyInstaller COLLECT` al escribir
`_internal/cryptography-50.0.2.dist-info/sboms/cryptography-rust.cyclonedx.json`.
El ejecutable ya se había construido, pero **el portable no estaba completo**.

La causa era una ruta física excesivamente larga bajo
`C:\\CitaHelper\\CacheCompilacion\\FuentesGitHub\\Personalizado-<SHA>\\Personalizado-<SHA>`.
El controlador actualizado conserva el ZIP del código fuente en la caché,
pero extrae y compila desde `C:\\CitaHelper\\s\\<12 caracteres del SHA>\\Personalizado-<SHA>`,
comprobando que la ruta del proyecto sea de como máximo 120 caracteres.

No hay que reinstalar dependencias ni descargar Camoufox o FPGen.
Solo hay que actualizar el pequeño archivo
`C:\\CitaHelper\\Proyecto\\Personalizado-final\\scripts\\compilar_portable.ps1`
y ejecutar de nuevo `C:\\CitaHelper\\CompilarPortable.bat`. El controlador
consulta la versión actual de GitHub y almacena en caché el nuevo ZIP
**del código**, no el navegador. Se conserva el intento fallido para
diagnóstico hasta finalizar la prueba en Windows.

La versión de PyInstaller observada en ese intento fue `6.22.3`, Python
`3.13.18`, hooks `2026.8` y Windows `10.0.19045`.
