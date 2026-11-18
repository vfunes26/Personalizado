# Validación final del portable personalizado en Windows

Este documento separa la **validación automática de GitHub Actions** de las
**pruebas reales del ejecutable Windows**. Estas últimas necesitan el ordenador
del usuario; no se simulan como si ya hubieran pasado.

## Condiciones previas para la compilación manual sin GitHub

- El código fuente actualizado se descarga manualmente del ZIP
  `https://github.com/vfunes26/Personalizado/archive/refs/heads/main.zip`.
  El BAT **no consulta GitHub**. Se necesita internet solamente para descargar
  tú mismo el ZIP si no lo tienes.
- Descomprime el nuevo código en
  `C:\\CitaHelper\\Proyecto\\Personalizado-nuevo` (o un nombre distinto
  dentro de `Proyecto`). **No sobrescribas**
  `C:\\CitaHelper\\Proyecto\\Personalizado-main` porque contiene
  `.venv` con las dependencias instaladas.
- Conserva Python 3.13.18 x64, PyInstaller 6.22.3, hooks 2026.8,
  PySide6, Playwright, Camoufox y FPGen del entorno probado.
- Camoufox: `%LOCALAPPDATA%\\camoufox\\camoufox\\Cache`.
  FPGen: `.venv\\Lib\\site-packages\\fpgen\\data` con los modelos y
  el marcador `.pinned-model`; cada SHA-256 debe coincidir.
- No es necesario abrir Visual Studio.

## Instalar los archivos ligeros del BAT

**No hace falta copiarlos a mano:** después de extraer el ZIP actualizado,
haz doble clic en `CompilarPortable.bat` **dentro de esa carpeta extraída**.
Detectará su directorio `scripts` y copiará a `C:\\CitaHelper` los cuatro
archivos pequeños necesarios:

- `CompilarPortable.bat` y `LimpiarPortable.bat`.
- `C:\\CitaHelper\\compilar_portable.ps1` y
  `C:\\CitaHelper\\limpiar_portable.ps1`.

Desde ese momento los BAT pueden moverse al Escritorio y seguirán funcionando.
La compilación también comienza desde el mismo doble clic.

## Compilación y verificación

1. Ejecutar `CompilarPortable.bat`. El controlador elige una carpeta
   descomprimida que contenga fuentes pero **no `.venv`** (para evitar
   compilar por accidente el código viejo de la carpeta de dependencias).
2. Comprueba Python y todos los modelos FPGen. No utiliza el descargador del
   navegador ni consulta GitHub.
3. Copia únicamente los directorios públicos de fuentes `app`, `scripts`,
   `catalogs`, `tests` y `.github`, más la documentación y metadatos
   requeridos, a una ruta temporal corta `C:\\CitaHelper\\s\\bXXXXXXXX\\src`.
   No copia `tasks.yml`, `data` ni `.venv`.
4. Compila con PyInstaller, ejecuta `scripts/verify_bundle.py`
   (GUI, Camoufox, Sigstore y trabajador IPC), genera ZIP local con su
   archivo SHA-256 y lo verifica antes de extraerlo.
5. Conserva íntegra una compilación anterior hasta que la nueva está preparada.
   Si hay datos privados de una compilación anterior, verifica que no haya
   SQLite WAL/SHM activo, los copia y compara SHA-256 archivo por archivo.
6. Tras instalar correctamente la nueva carpeta
   `C:\\CitaHelper\\Compilaciones\\Cita Extranjeria Helper - Personalizado`,
   elimina el ZIP, el `data/dist` y los temporales **del intento actual**.
   No conserva copia ZIP de la misma compilación.
7. Abre manualmente el ejecutable nuevo y termina las pruebas funcionales.

## Limpieza final después de probar

Solo después de comprobar que el nuevo ejecutable abre y funciona:

- Haz doble clic en `LimpiarPortable.bat`, o ejecuta
  `CompilarPortable.bat /limpiar`.
- El controlador comprobará el portable y pedirá escribir `LIMPIAR`.
- Elimina `Compilaciones\\Paquetes`, `Compilaciones\\.preparando-*`,
  temporales conocidos `s`, la caché antigua de fuente
  `CacheCompilacion\\FuentesGitHub`, el ZIP antiguo
  `CacheCompilacion\\Personalizado-final16.zip`, la extracción temporal
  `ExtraerFinal16` y fuentes manuales `Proyecto\\Personalizado-*`
  siempre que **no** contengan `.venv`, `tasks.yml`, `data` ni `.git`.
- **Nunca elimina** `Proyecto\\Personalizado-main` mientras tenga `.venv`,
  ni `CacheCompilacion\\Camoufox`, `CacheCompilacion\\Fpgen`,
  `CacheCompilacion\\CacheUV`, `RespaldosPrivados`,
  `Compilaciones\\Respaldos`, el portable final o el portable original
  del Escritorio.

**Por qué queda `.venv`:** contiene dependencias instaladas con rutas Windows.
Borrarlo haría imposible volver a compilar sin reinstalar esos paquetes.
El objetivo de conservar solamente el portable se cumple haciendo una copia
de seguridad **solo de su carpeta descomprimida**.

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


## Histórico de la corrección de ruta larga

El primer intento de la versión 0.3.5 falló en la fase de PyInstaller
`COLLECT` por rutas excesivamente largas de `cryptography`.
Un intento posterior usando una ruta corta completó `COLLECT`,
`verify_bundle.py` y el ZIP portable de Windows correctamente.

La modalidad manual mantiene la solución usando una raíz temporal corta
`C:\\CitaHelper\\s\\bXXXXXXXX\\src`. No es necesario reinstalar Camoufox
ni FPGen por este problema.
