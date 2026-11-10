# Cita Extranjería Helper — versión personalizada

Añade tres cosas al proyecto original **sin tocar** su funcionamiento actual:

| Novedad | Qué hace |
|---|---|
| **Acceso «Sin Cl@ve»** | Cuarta opción en *Método de acceso*. Pulsa «Presentación sin Cl@ve» (`#btnEntrar`) y sigue el mismo flujo de siempre. |
| **Perfiles por Telegram** | Envías un bloque de texto a tu bot y la app crea el perfil. `/start` te devuelve la plantilla. |
| **Alertas más precisas** | Aviso de **Cod. Oper** (no insistir hasta las 00:00 de Madrid), aviso de **«sin citas sin Cl@ve, con Cl@ve sí hay»** y oficina preferida marcada con ⭐. |

Las pausas, el presupuesto de intentos y el CAPTCHA/confirmación **manuales** quedan exactamente como estaban.

---

## 1. Puesta en marcha en tu PC (local)

1. Aplica el cambio sobre tu fork: `git apply custom-changes.patch` (o usa el zip del proyecto ya modificado).
2. Instala y arranca desde el código (en Windows el README original indica usar WSL con soporte gráfico):
   ```sh
   uv python install 3.13
   uv sync --frozen --python 3.13 --extra desktop
   uv run python -m camoufox fetch
   uv run python -m app.main desktop
   ```
3. Pruebas automáticas: `uv sync --group dev` y `uv run pytest`.
4. **Portable de Windows propio:** sin instalar nada en tu PC, con GitHub Actions: ver la sección 11.
5. **Importante en tu repositorio:** cambia `REPOSITORY` y `API` en `app/desktop/updates.py` a tu repositorio, o desactiva *Comprobar actualizaciones automáticamente* en Ajustes. Si no, la app te ofrecerá la versión del autor original y sobrescribiría tus cambios.

## 2. Primer uso del bot (una sola vez)

1. Crea el bot con **@BotFather** y copia el token (guía anterior).
2. En un perfil: *Ajustes → Editar perfil → Notificaciones* → activa Telegram, pega el token, **Comprobar**, conecta tu chat con **+** (pulsa *Start* en el bot) y **guarda**. Tu chat privado queda como *destinatario autorizado*.
3. *Ajustes → Telegram →* activa **Crear perfiles desde Telegram**.
4. Abre tu bot y escribe `/start`: te responde con la plantilla.

> Mientras vinculas un destinatario (los 5 minutos del enlace) no envíes plantillas; el buzón deja intacto el mensaje de vinculación, pero conviene no mezclar ambas cosas.

## 3. La plantilla

Una línea por campo, formato `CLAVE: valor`. Mayúsculas/minúsculas y tildes dan igual en las claves y en los códigos.

```
PERFIL: Mi perfil (opcional)
TRAMITE: TIE
PROVINCIA: 08
OFICINA: CUALQUIERA
ACCESO: SIN_CLAVE
NIE: X1234567L
NOMBRE: MARIA LOPEZ GARCIA
NACIONALIDAD: PERU
TELEFONO: 600123456
EMAIL: nombre@correo.com
```

| Campo | Valores | Notas |
|---|---|---|
| `TRAMITE` | `TIE` (POLICÍA-TOMA DE HUELLAS… LEY 14/2013) · `REGRESO` | También acepta el nombre oficial completo |
| `PROVINCIA` | Nombre (`Barcelona`), alias (`BCN`, `MAD`) o **código INE de 2 dígitos** (`08`) | `/provincias` lista todas |
| `OFICINA` | `CUALQUIERA` · parte del nombre (`GRANOLLERS`) · número de `/oficinas` | Solo Barcelona se verifica contra el catálogo; en otras provincias se guarda como preferencia |
| `ACCESO` | `CERTIFICADO` · `CLAVE_MOVIL` · `CLAVE_PERMANENTE` · `SIN_CLAVE` | `CLAVE` a secas es ambiguo y se rechaza |
| `NIE` | `X1234567L` | Se valida la letra de control. Con `REGRESO` puede usarse `DNI:` o `PASAPORTE:` |
| `NOMBRE` | Letras y espacios, máx. 50 | Se pasa a MAYÚSCULAS sin tildes ni Ñ |
| `NACIONALIDAD` | Como en el catálogo (`PERU`) | Se aceptan tildes y minúsculas; si es ambiguo, el bot lista opciones |
| `TELEFONO` | 6–15 dígitos | Se ignoran espacios, guiones y `+` |
| `EMAIL` | Dirección válida | Se guarda en minúsculas |
| `RELLENO` (opcional) | `MANUAL` (por defecto) · `ACCESO` | `ACCESO` copia los datos de la web tras entrar; **no** con `SIN_CLAVE` |

Comandos: `/start` `/plantilla` (formato) · `/provincias` · `/oficinas` · `/perfiles` (nombres, sin datos personales).

**Respuestas:** `✅ Perfil creado` con un resumen **enmascarado** (NIE `X******7L`, nombre en iniciales, correo `m***@…`); `⚠` con **todos** los errores a la vez; `ℹ` si ya existe un perfil con el mismo documento+trámite+provincia+acceso.

## 4. Oficina: cualquiera o específica

El portal siempre te deja elegir la oficina a ti. El helper ya avisa por Telegram con **todas las oficinas que tienen cita**. Con `OFICINA: CUALQUIERA` recibes esa lista tal cual. Con una oficina concreta, el aviso es el mismo pero la tuya aparece **primero y con ⭐** (y una línea «Tu oficina preferida está disponible»). La elección y la reserva siguen siendo manuales.

## 5. «Sin Cl@ve»

- La app abre el portal, pulsa **Presentación sin Cl@ve** y rellena el formulario de datos igual que con certificado/Cl@ve. No hace falta certificado instalado.
- Es una **bolsa de citas distinta**: puede estar vacía aunque con Cl@ve haya citas (tu Figura 1). Cuando eso ocurre recibes el aviso «No hay citas sin Cl@ve: con Cl@ve sí hay».
- **El presupuesto de intentos es por documento (NIE), no por perfil**: un perfil con Cl@ve y otro sin Cl@ve del mismo NIE comparten el contador. Alternar no da intentos extra y no debe usarse para eso.
- El certificado, si lo usas en otros perfiles, se instala **en Windows** (doble clic en el `.pfx`); Camoufox lo lee del almacén del sistema. No lo copies al proyecto ni lo subas a GitHub.

## 6. Alertas nuevas

| Situación en el portal | Qué ves / recibes |
|---|---|
| Aparece **Cod. Oper** | La pausa existente sigue igual; el estado pasa a *«Pausa tras cod. oper — se recomienda no continuar hasta las 00:00 (Madrid)»* y por Telegram: aviso con la hora actual de Madrid y el tiempo que falta. Máx. 1 aviso cada 30 min. |
| «No hay citas para la reserva sin Cl@ve… SÍ con Cl@ve» | Estado y aviso «Sin citas sin Cl@ve; con Cl@ve sí hay». Máx. 1 por hora. |
| Oficina preferida disponible | ⭐ en la lista de oficinas |

Las dos primeras son **eventos nuevos** (*Restricción del NIE* y *Sin citas sin Cl@ve*): aparecen como casillas en *Notificaciones* y los perfiles creados por el bot ya los traen activados. En perfiles antiguos actívalos a mano. La regla «se levanta a medianoche» procede de la comunidad, no es oficial.

## 7. Seguridad y privacidad

- Solo **chats privados ya vinculados** como destinatarios pueden usar el bot; el resto es ignorado sin respuesta.
- El token vive en el **almacén de credenciales del sistema**, nunca en YAML. Cada perfil nuevo recibe su propia copia, para que borrar un perfil no rompa otro.
- El bot **solo crea perfiles**: no inicia búsquedas, no lee ni borra perfiles.
- Tras procesar, **borra tu mensaje** del chat (si Telegram lo permite) y responde solo con datos enmascarados. Aun así, el mensaje pasó por los servidores de Telegram: no envíes datos que no quieras que tengan.
- Límite de 10 perfiles por hora, aunque el chat esté autorizado.
- Si tu token se filtra: `/revoke` en @BotFather y reconéctalo.

## 8. Qué no hace / límites conocidos

- Solo funciona **con la app abierta** y con el interruptor activado (sondeo local cada 3 s, sin servidor).
- No automatiza CAPTCHA, elección de fecha ni confirmación, ni elude restricciones del portal.
- No puede usarse con un bot que tenga **webhook** de otro servicio (el buzón se desactiva y lo indica).
- La rama «Sin Cl@ve» está escrita a partir de tus HTML capturados; **debe probarse una vez contra el portal real** (ver sección 9).

## 9. Primera prueba recomendada

1. Activa *Diagnóstico* en Ajustes.
2. Crea un perfil Sin Cl@ve (por Telegram o a mano) y pulsa **Iniciar** con los intervalos por defecto.
3. Comprueba que pulsa «Presentación sin Cl@ve» y llega al formulario de datos. Si el portal cambió los identificadores y la app se detiene en «estructura del sitio cambió», usa *Copiar informe* (sin datos personales) para ajustar `_enter_without_clave` en `app/site.py`.

## 10. Archivos

**Nuevos:** `app/profile_intake.py` (plantilla y validación), `app/telegram_inbox.py` (buzón), `tests/test_profile_intake.py`, `tests/test_telegram_inbox.py`, `tests/test_without_clave_and_alerts.py`.
**Modificados:** `app/site.py` (`_enter_without_clave`), `app/assist_flow.py`, `app/notifications.py`, `app/desktop/{profiles,worker,window,notification_delivery}.py`, `app/desktop/assets/translations.json`.

Licencia: se mantiene **PolyForm Noncommercial 1.0.0** y el aviso de autoría del proyecto original.

---

## 11. Repositorio nuevo, portable de Windows y navegador

### ¿Repositorio nuevo o fork?
**Recomendado: repositorio nuevo (independiente).** Es privado si quieres, tiene historial propio y nada de lo que subas llega al original. Un fork de un repo público siempre es público y sigue enlazado al autor. Lo que pierdes con el repo nuevo es el botón «Sync fork»: las mejoras futuras del autor las tendrías que traer a mano. Mantén los archivos `LICENSE` y el aviso de autoría (PolyForm Noncommercial) y menciona el proyecto original en tu README.

### Subirlo (con Git, no arrastrando carpetas)
Descomprime el zip y, dentro de la carpeta `extranjeria-cita-helper-main`:
```sh
git init -b main
git add .
git commit -m "Versión personalizada basada en extranjeria-cita-helper 0.3.5"
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```
Crea antes el repositorio vacío en GitHub (sin README). Usa Git o GitHub Desktop: la subida por navegador suele omitir carpetas ocultas como `.github`, que contiene el workflow.

### Generar el portable (no es una ISO: es un ZIP)
1. En GitHub: **Actions → Build Windows portable (personal) → Run workflow**. Si GitHub lo pide, acepta «I understand my workflows, go ahead and enable them».
2. Espera (≈20–40 min). Si falla la fase *Test*, no hay paquete: copia el error, o relanza con *run_tests* desmarcado para empaquetar igualmente.
3. Abre la ejecución terminada → al final, **Artifacts → windows-portable** → descarga. Está disponible 14 días.
4. Descomprime (el archivo descargado contiene el `…-portable.zip`), descomprime ese también y ejecuta el `.exe`. Tus datos quedan en una carpeta junto a la app.

Notas: el workflow solo se lanza a mano. No crees etiquetas `v*` (lanzan el workflow original de 4 plataformas y una release) o desactiva ese workflow en *Actions*. En repos privados, los minutos de Windows consumen el cupo gratuito mensual a doble ritmo.

### El navegador
Se llama **Camoufox** (un Firefox preparado para automatización). No se elige como «navegador predeterminado» de Windows: la app abre **su propia copia**. Va **dentro** del portable y por eso pesa ~700 MB; es lo recomendable, porque así cada versión usa el navegador con el que fue probada. El ajuste `browser_executable_path` solo admite Chromium, que el programa no usa. Quitar Camoufox del paquete exigiría modificar el código para descargarlo en el primer arranque, con más riesgo de fallos, a cambio de ahorrar solo tamaño de descarga.
