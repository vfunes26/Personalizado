"""Create profiles from Telegram messages. Runs locally: long-polling, no server.

Security model
--------------
* Only **private chats that are already paired as recipients** of a Telegram
  connection in the app may talk to the inbox. Everybody else is ignored silently.
* The token is read from the system credential store; it is never written to YAML.
* The bot can create and list profiles and delete after explicit confirmation.
  Deletion is limited to paired private chats, blocked while a worker runs,
  and requires an authenticated Gmail notification configuration.
* The profile-submission flow and its best-effort input deletion are unchanged.
* A bounded number of profiles per hour can be created, even for allowed chats.
"""
from __future__ import annotations

import copy
import logging
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from .notifications import EVENTS, NotificationError, PAIRING_LIFETIME_SECONDS, Telegram, settings as notification_settings
from .profile_intake import (Catalog, looks_like_submission, offices_text, parse_submission,
                             provinces_text, template_text)
from .desktop.profile_deletion import ProfileDeletionService, ProfileDeletionError

log = logging.getLogger(__name__)

MAX_CREATED_PER_HOUR = 10
HELP_COMMANDS = {'/start', '/ayuda', '/help', '/plantilla', '/perfil'}
HOLD_SECONDS = PAIRING_LIFETIME_SECONDS + 30
DELETE_CONFIRM_SECONDS = 180


class Source:
    """Telegram connection used by the inbox (token + chats that are allowed)."""

    def __init__(self, profile_id, token, recipients, events):
        self.profile_id, self.token = profile_id, token
        self.recipients = tuple(copy.deepcopy(r) for r in recipients)
        self.events = tuple(events)

    @property
    def allowed_chats(self):
        return {str(r['id']) for r in self.recipients if r.get('type', 'private') == 'private'}


def find_source(store, vault, preferred_id=None):
    """First profile with Telegram enabled, a token and at least one private recipient."""
    tasks = store.load()
    ordered = sorted(tasks, key=lambda t: (t.id != preferred_id,))
    for task in ordered:
        try:
            config = notification_settings(store.raw_profile(task.id).get('notifications', {}))['telegram']
        except (ValueError, StopIteration):
            continue
        if not config.get('enabled') or not config.get('secret_ref') or not config.get('recipients'):
            continue
        try:
            token = vault.get(config['secret_ref']).get('token', '')
        except NotificationError:
            continue
        source = Source(task.id, token, config['recipients'], config.get('events') or EVENTS)
        if token and source.allowed_chats:
            return source
    return None


class TelegramInbox:
    def __init__(self, store, vault, *, client=None, now=time.monotonic, catalog=None,
                 delete_submissions=True, deletion_service=None):
        self.store, self.vault, self.now = store, vault, now
        self.catalog = catalog or Catalog.load(Path(store.catalog_path))
        self.client = client
        self._injected_client = client is not None
        self.source = None
        self.delete_submissions = delete_submissions
        self.disabled_reason = ''
        self.offset = None
        self.handled = set()
        self.held = {}
        self.created = deque()
        self.deletion_service = deletion_service or ProfileDeletionService(store, vault=vault)
        # Keys are authorized private chat IDs; all values expire automatically.
        self.listings = {}
        self.pending_deletions = {}

    # ------------------------------------------------------------------ setup
    def prepare(self):
        """Resolve token/chats. Returns False (with ``disabled_reason``) if the inbox cannot run."""
        source = find_source(self.store, self.vault)
        if source is None:
            self.disabled_reason = 'Conecte un destinatario de Telegram en un perfil (Notificaciones) para usar el buzón.'
            return False
        if not self._injected_client:
            self.client = Telegram(source.token)
        self.source = source
        try:
            if self.client.call('getWebhookInfo').get('url'):
                self.disabled_reason = 'El bot usa un webhook de otro servicio; use un bot separado.'
                return False
        except NotificationError:
            self.disabled_reason = 'No se pudo consultar Telegram.'
            return False
        self.disabled_reason = ''
        return True

    # -------------------------------------------------------------- polling
    def _next_offset(self):
        self.held = {uid: t for uid, t in self.held.items() if self.now() - t < HOLD_SECONDS}
        if self.held:
            return min(self.held)  # never confirm a pending pairing /start
        return None if self.offset is None else self.offset

    def poll_once(self):
        if self.source is None and not self.prepare():
            return 0
        data = {'timeout': 0, 'limit': 50, 'allowed_updates': ['message', 'callback_query']}
        offset = self._next_offset()
        if offset is not None:
            data['offset'] = offset
        updates = self.client.call('getUpdates', data)
        handled_now = 0
        for update in updates:
            uid = int(update.get('update_id', 0))
            self.offset = max(self.offset or 0, uid + 1)
            if uid in self.handled:
                continue
            self.handled.add(uid)
            message = update.get('message') or {}
            text = message.get('text') or ''
            if text.startswith('/start') and len(text.split()) > 1:
                self.held[uid] = self.now()  # deep-link pairing code: leave it for the pairing dialog
                continue
            try:
                callback = update.get('callback_query')
                handled_now += bool(self.handle_callback(callback)) if callback else bool(self.handle_message(message))
            except NotificationError:
                log.warning('telegram_inbox_reply_failed')
        if len(self.handled) > 2000:
            self.handled = set(sorted(self.handled)[-1000:])
        return handled_now

    # -------------------------------------------------------------- messages
    def handle_message(self, message):
        chat = message.get('chat') or {}
        chat_id = str(chat.get('id', ''))
        if chat.get('type') != 'private' or chat_id not in self.source.allowed_chats:
            return False  # silent: never reveal the bot to strangers
        text = (message.get('text') or '').strip()
        if not text:
            return False
        command = text.split()[0].split('@')[0].lower() if text.startswith('/') else ''
        if command in {'/provincias'}:
            return self._reply(chat_id, provinces_text(self.catalog))
        if command in {'/oficinas'}:
            return self._reply(chat_id, offices_text(self.catalog))
        if command in {'/perfiles'}:
            return self._reply(chat_id, self._profiles_text(chat_id))
        if command == '/borrar':
            return self._request_deletion(chat_id, text)
        if looks_like_submission(text):
            return self._submission(chat_id, message, text)
        if command in HELP_COMMANDS or not command:
            return self._reply(chat_id, template_text())
        return self._reply(chat_id, 'Comando no reconocido. Use /plantilla, /provincias, /oficinas, /perfiles o /borrar N.')

    def _reply(self, chat_id, text):
        self.client.send(chat_id, text[:4000])
        return True

    def _profiles_text(self, chat_id=None):
        try:
            tasks = self.store.load()
            revision = self.store.revision()
        except ValueError:
            return 'No se pudo leer la lista de perfiles.'
        if chat_id is not None:
            self.listings[str(chat_id)] = (revision, tuple(t.id for t in tasks))
        if not tasks:
            return 'No hay perfiles.'
        items = (f'{index}. {t.label} ({t.province})' +
                 (' ⚠ revisar datos' if t.errors else '')
                 for index, t in enumerate(tasks, 1))
        return ('Perfiles (número de esta lista, no parte del nombre):\n' +
                '\n'.join(items) +
                '\n\nPara eliminar: /borrar 2. Se pedirá confirmación.')

    def _request_deletion(self, chat_id, text):
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdecimal() or len(parts[1]) > 3:
            return self._reply(chat_id, 'Uso: /perfiles y después /borrar 2.')
        index = int(parts[1])
        try:
            tasks = self.store.load()
            revision = self.store.revision()
            if chat_id in self.listings:
                saved_rev, saved_ids = self.listings[chat_id]
                if saved_rev != revision or saved_ids != tuple(t.id for t in tasks):
                    self.listings.pop(chat_id, None)
                    return self._reply(chat_id, 'La lista cambió. Envía /perfiles para ver la numeración actual.')
        except ValueError:
            return self._reply(chat_id, 'No se pudieron leer los perfiles.')
        if not 1 <= index <= len(tasks):
            return self._reply(chat_id, 'Número fuera de rango. Envía /perfiles para ver la lista.')
        target = tasks[index - 1]
        if self.source and target.id == self.source.profile_id:
            return self._reply(chat_id, 'No se puede borrar el perfil que mantiene conectado este bot.')
        try:
            mail = self.deletion_service.mail.read()
            if not mail.get('secret_ref') or not mail.get('recipients'):
                return self._reply(chat_id, 'Configura Gmail en la aplicación antes de eliminar perfiles.')
        except NotificationError:
            return self._reply(chat_id, 'Configura Gmail en la aplicación antes de eliminar perfiles.')
        token = secrets.token_hex(8)
        self.pending_deletions[chat_id] = {
            'token': token, 'profile_id': target.id, 'revision': revision,
            'label': target.label, 'created': self.now(),
        }
        buttons = {'inline_keyboard': [[
            {'text': '✅ Confirmar eliminación', 'callback_data': 'cehdel:yes:' + token},
            {'text': 'Cancelar', 'callback_data': 'cehdel:no:' + token},
        ]]}
        try:
            response = self.client.call('sendMessage', {
                'chat_id': chat_id, 'text': (
                    f'¿Eliminar el perfil {index}: «{target.label}»?\n'
                    'Esta acción requiere confirmación y quedará registrada.'
                ), 'reply_markup': buttons,
            })
            self.pending_deletions[chat_id]['message_id'] = (
                response.get('message_id') if isinstance(response, dict) else None)
        except NotificationError:
            self.pending_deletions.pop(chat_id, None)
            raise
        return True

    def handle_callback(self, callback):
        if not isinstance(callback, dict):
            return False
        data = callback.get('data', '')
        if not isinstance(data, str) or not data.startswith('cehdel:'):
            return False
        message = callback.get('message') or {}
        chat = message.get('chat') or {}
        chat_id = str(chat.get('id', ''))
        sender_id = str((callback.get('from') or {}).get('id', ''))
        if (chat.get('type') != 'private' or chat_id not in self.source.allowed_chats
                or chat_id != sender_id):
            return False
        try:
            self.client.call('answerCallbackQuery', {'callback_query_id': callback['id']})
        except NotificationError:
            pass
        parts = data.split(':')
        pending = self.pending_deletions.get(chat_id)
        if (len(parts) != 3 or parts[1] not in {'yes', 'no'} or
                pending is None or pending['token'] != parts[2] or
                (pending.get('message_id') is not None and
                 pending['message_id'] != message.get('message_id'))):
            return self._reply(chat_id, 'Confirmación inválida o caducada. Envía /perfiles y repite la solicitud.')
        self.pending_deletions.pop(chat_id, None)
        try:
            self.client.call('editMessageReplyMarkup', {
                'chat_id': chat_id, 'message_id': message.get('message_id'),
                'reply_markup': {'inline_keyboard': []},
            })
        except NotificationError:
            pass
        if parts[1] == 'no':
            return self._reply(chat_id, 'Eliminación cancelada. No se modificó ningún perfil.')
        if self.now() - pending['created'] > DELETE_CONFIRM_SECONDS:
            return self._reply(chat_id, 'Confirmación caducada. Envía /perfiles y vuelve a solicitarla.')
        if self.source and pending['profile_id'] == self.source.profile_id:
            return self._reply(chat_id, 'No se puede borrar el perfil que mantiene conectado el bot.')
        try:
            result = self.deletion_service.delete(
                pending['profile_id'], revision=pending['revision'],
                origin='telegram', protected_profile_id=self.source.profile_id,
            )
        except ProfileDeletionError as exc:
            return self._reply(chat_id, str(exc))
        self.listings.pop(chat_id, None)
        suffix = ('Comprobante enviado por Gmail.' if result['emailed'] else
                  'El correo no pudo enviarse; consulta la auditoría local.')
        if result['warnings']:
            suffix += ' Algunas asignaciones locales requieren revisión.'
        return self._reply(chat_id, '✅ Perfil eliminado: «' + pending['label'] + '».\n' + suffix)

    def _submission(self, chat_id, message, text):
        try:
            self._rate_limit()
            result = parse_submission(text, self.catalog)
            if not result.ok:
                self._reply(chat_id, '⚠ No se creó el perfil:\n\n' + '\n'.join('• ' + e for e in result.errors)
                            + '\n\nCorrija y reenvíe el bloque completo. /plantilla muestra el formato.')
                return True
            duplicate = self._duplicate(result.identity)
            if duplicate:
                self._reply(chat_id, f'ℹ Ya existe un perfil con ese documento, trámite, provincia y acceso: «{duplicate}». No se creó otro.')
                return True
            profile_id = self._create(result.fields)
            extra = ('\n\n' + '\n'.join('ℹ ' + w for w in result.warnings)) if result.warnings else ''
            self._reply(chat_id, '✅ Perfil creado\n\n' + (result.full_summary or result.summary) + extra
                        + '\n\nYa aparece en la app. Inicie la búsqueda desde allí (Seguimiento → Iniciar).')
            log.info('telegram_inbox_profile_created', extra={'profile_id': profile_id})
        except RuntimeError as exc:
            self._reply(chat_id, '⛔ ' + str(exc))
        except (ValueError, OSError) as exc:
            log.warning('telegram_inbox_create_failed: %s', type(exc).__name__)
            self._reply(chat_id, '⚠ No se pudo guardar el perfil. Revise los datos o intente de nuevo.')
        finally:
            self._delete(chat_id, message)
        return True

    def _rate_limit(self):
        now = self.now()
        while self.created and now - self.created[0] > 3600:
            self.created.popleft()
        if len(self.created) >= MAX_CREATED_PER_HOUR:
            raise RuntimeError('Límite de perfiles por hora alcanzado. Espere antes de crear más.')

    def _duplicate(self, identity):
        number, procedure, province, access_mode = identity
        for task in self.store.load():
            if (task.document_number, task.procedure, task.province, task.access_mode) == (number, procedure, province, access_mode):
                return task.label
        return None

    def _create(self, fields):
        """Save with its own copy of the token so deleting one profile never breaks another."""
        reference = self.vault.put({'token': self.source.token})
        notifications = {'telegram': {'enabled': True, 'events': list(EVENTS),
                                      'recipients': copy.deepcopy(list(self.source.recipients)),
                                      'secret_ref': reference}}
        payload = dict(fields, notifications=notifications)
        try:
            for attempt in range(2):
                try:
                    profile_id = self.store.save_profile(None, payload, revision=self.store.revision())
                    self.created.append(self.now())
                    return profile_id
                except Exception as exc:  # noqa: BLE001 - retry only on edit conflicts
                    if type(exc).__name__ != 'ProfileConflictError' or attempt:
                        raise
        except Exception:
            self.vault.delete(reference)
            raise

    def _delete(self, chat_id, message):
        if not self.delete_submissions or 'message_id' not in message:
            return
        try:
            self.client.call('deleteMessage', {'chat_id': chat_id, 'message_id': message['message_id']})
        except NotificationError:
            pass


class InboxThread(threading.Thread):
    """Background poller; ``stop()`` ends it within one interval."""

    def __init__(self, inbox, *, interval=3.0):
        super().__init__(name='telegram-inbox', daemon=True)
        self.inbox, self.interval = inbox, interval
        self._stop_event = threading.Event()
        self.last_error = ''

    def run(self):
        failures = 0
        while not self._stop_event.is_set():
            try:
                self.inbox.poll_once()
                failures = 0
                self.last_error = self.inbox.disabled_reason
            except Exception as exc:  # noqa: BLE001 - keep the app alive, never log request data
                failures += 1
                self.last_error = type(exc).__name__
                log.warning('telegram_inbox_poll_failed: %s', type(exc).__name__)
            wait = self.interval if not failures else min(60.0, self.interval * 2 ** min(failures, 5))
            if self.inbox.disabled_reason:
                wait = max(wait, 30.0)  # e.g. no recipient yet: retry slowly
                self.inbox.source = None
            self._stop_event.wait(wait)

    def stop(self):
        self._stop_event.set()
