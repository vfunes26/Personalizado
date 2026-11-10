# Gestión de proxies fijos por perfil de solicitud

## 1. Objetivo

La aplicación permite configurar varios servidores proxy y asignar exactamente uno a cada perfil de solicitud. La selección es fija: no existe rotación, balanceo, reparto aleatorio ni cambio automático entre proxies.

El proxy se aplica únicamente al navegador Camoufox asociado al perfil de solicitud que lo tenga asignado y activado.

## 2. Reglas de funcionamiento

| Estado del perfil | Comportamiento |
|---|---|
| No tiene proxy asignado | Camoufox utiliza la conexión normal del equipo |
| Tiene proxy asignado, pero está desactivado | Camoufox utiliza la conexión normal del equipo |
| Tiene proxy asignado y está activado | Camoufox utiliza exclusivamente ese proxy |
| El proxy activo no responde | La conexión falla; no se realiza fallback silencioso a conexión directa |

Cada perfil de solicitud mantiene su propia asignación. Dos perfiles pueden usar el mismo proxy si se les asigna expresamente, pero la aplicación no cambia automáticamente sus asignaciones.

## 3. Arquitectura

### `app/desktop/proxy_profiles.py`

Contiene `ProxyProfileStore`, responsable de:

- Leer y escribir el archivo JSON de proxies.
- Crear y actualizar perfiles proxy.
- Eliminar proxies y limpiar sus asignaciones.
- Vincular un proxy a un perfil de solicitud.
- Activar o desactivar la vinculación.
- Resolver el proxy efectivo de un perfil de solicitud.
- Validar los endpoints antes de guardarlos.

La clase principal expone, entre otros, estos métodos:

- `load()`
- `save_proxy_profile(profile_id, fields)`
- `delete_proxy_profile(proxy_id)`
- `bind_request_profile(request_profile_id, proxy_profile_id, enabled=...)`
- `assignment_for(request_profile_id)`
- `proxy_for_request(request_profile_id)`

La validación admite los esquemas `http`, `https` y `socks5`. El endpoint debe incluir servidor y puerto. Las credenciales se introducen en sus campos separados, no dentro de la URL.

### `app/desktop/window.py`

Integra la pestaña **Proxy** en el editor de perfiles de solicitud. Desde esa pestaña se puede:

- Seleccionar un proxy existente.
- Crear un proxy.
- Editar sus datos.
- Eliminarlo.
- Activar o desactivar su uso para el perfil que se está editando.

La configuración de proxies se guarda de forma independiente de los datos de solicitud existentes.

### `app/site.py`

La función `_camoufox_proxy_options(task_id)` consulta la asignación correspondiente al ID del perfil de solicitud.

- Si no hay proxy activo, devuelve un diccionario vacío y no añade opciones de proxy.
- Si hay un proxy activo, construye las opciones `server`, `username` y `password` disponibles.
- `_launch_camoufox()` incorpora esas opciones a la configuración de lanzamiento de Camoufox.

No se requiere cambiar el worker ni el flujo de navegación: el ID del perfil de solicitud ya se entrega al runtime.

### `app/desktop/paths.py`

`runtime_root()` determina la raíz de ejecución utilizada para localizar los datos de la aplicación.

## 4. Archivo de configuración

La configuración se guarda en:

```text
runtime_root()/data/proxy-profiles.json
```

Ejemplo ilustrativo:

```json
{
  "proxy_profiles": [
    {
      "id": "proxy-id",
      "label": "Proxy principal",
      "server": "http://127.0.0.1:8080",
      "username": "usuario",
      "password": "clave"
    }
  ],
  "assignments": {
    "request-profile-id": {
      "proxy_profile_id": "proxy-id",
      "enabled": true
    }
  }
}
```

Los identificadores del ejemplo son ilustrativos. La aplicación genera y administra los identificadores reales.

El archivo se crea o actualiza cuando se guardan perfiles proxy o sus asignaciones. No se debe editar mientras la aplicación está escribiendo en él.

## 5. Configuración desde la aplicación

1. Abre el editor del perfil de solicitud.
2. Entra en la pestaña **Proxy**.
3. Pulsa **Nuevo** para crear un proxy.
4. Introduce un nombre descriptivo.
5. Introduce el servidor con protocolo y puerto, por ejemplo `http://host:8080` o `socks5://host:1080`.
6. Si el servidor requiere autenticación, completa usuario y contraseña.
7. Pulsa **Guardar proxy**.
8. Selecciona el proxy que acabas de guardar.
9. Activa **Usar proxy en este perfil**.
10. Guarda el perfil de solicitud.

Para usar conexión directa, desactiva **Usar proxy en este perfil** o selecciona **Sin proxy** y guarda el perfil.

## 6. Administración y cambios

- **Editar:** selecciona el proxy en la lista, modifica los campos y pulsa **Guardar proxy**.
- **Crear otro:** pulsa **Nuevo**, completa los datos y guarda.
- **Desactivar para un perfil:** desmarca la opción de uso y guarda el perfil.
- **Eliminar:** selecciona el proxy y pulsa **Eliminar proxy**. La eliminación también limpia las asignaciones que apuntaban a ese proxy.
- **Cambiar de proxy:** selecciona otro proxy en el perfil y guarda.

La asignación es por perfil de solicitud, no por ejecución individual ni por sesión aleatoria.

## 7. Validación y errores

Se rechazan, entre otros, endpoints que:

- No incluyan protocolo.
- Utilicen un protocolo no admitido.
- No incluyan puerto.
- Incluyan credenciales dentro de la URL.
- Incluyan rutas o parámetros adicionales no permitidos.

Si un proxy está activado y no puede establecer conexión, no debe interpretarse como una orden para conectarse directamente. La conexión directa solo corresponde al caso en que no hay proxy asignado o la asignación está desactivada.

## 8. Seguridad

**Importante:** en la implementación actual, el usuario y la contraseña se almacenan en texto claro dentro de `proxy-profiles.json`.

Medidas recomendadas:

- Restringir los permisos de lectura del directorio de datos al usuario del sistema que ejecuta la aplicación.
- No compartir el archivo JSON ni adjuntarlo a incidencias públicas.
- No incluir credenciales reales en capturas, registros, pruebas ni commits.
- Utilizar credenciales de proxy con permisos limitados cuando el proveedor lo permita.

La ocultación visual de la contraseña en el campo de la interfaz no cifra el valor almacenado en el archivo.

## 9. Pruebas

Después de aplicar las integraciones de pruebas, ejecutar primero:

```bash
pytest -q tests/test_proxy_profiles.py tests/test_site.py tests/test_desktop_ui.py
```

Si el conjunto anterior termina correctamente, ejecutar la suite completa:

```bash
pytest -q
```

Las pruebas cubren:

- Separación de proxies entre perfiles de solicitud.
- Comportamiento sin proxy y con asignación desactivada.
- Rechazo de asignaciones inválidas.
- Validación de endpoints.
- Limpieza de asignaciones al eliminar un proxy.
- Entrega a Camoufox únicamente del proxy activo asignado.
- Omisión de credenciales vacías.
- Guardado y recuperación de la asignación desde la interfaz.

## 10. Alcance y preservación de la aplicación

Esta funcionalidad está diseñada para mantener intactos:

- El worker y la secuencia de ejecución.
- El flujo de navegación existente.
- El almacenamiento YAML de perfiles de solicitud.
- Las notificaciones y la integración con Telegram.
- Las alertas y demás funciones de la aplicación.
- La distribución portable de Camoufox.

La configuración de proxy permanece aislada en su propio archivo JSON y se consulta al preparar el lanzamiento del navegador.
