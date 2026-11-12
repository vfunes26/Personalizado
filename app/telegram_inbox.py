"""Create profiles from Telegram messages. Runs locally: long-polling, no server.

Security model
--------------
* Only **private chats that are already paired as recipients** of a Telegram
  connection in the app may talk to the inbox. Everybody else is ignored silently.
* The token is read from the system credential store; it is never written to YAML.
* The bot only creates profiles. It cannot start a search, read profiles back or
  delete anything. Replies contain masked data only, and the incoming message is
  deleted (best effort) so personal data does not stay in the chat.
* A bounded number of profiles per hour can be created, even for allowed chats.
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from collections import deque
from pathlib import Path

from .notifications import EVENTS, NotificationError, PAIRING_LIFETIME_SECONDS, Telegram, settings as notification_settings
from .profile_intake import (Catalog, looks_like_submission, offices_text, parse_submission,
                             provinces_text, template_text)

log = logging.getLogger(__name__)

MAX_CREATED_PER_HOUR = 10
HELP_COMMANDS = {'/start', '/ayuda', '/help', '/plantilla', '/perfil'}
HOLD_SECONDS = PAIRING_LIFETIME_SECONDS + 30


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
                 delete_submissions=True):
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
        data = {'timeout': 0, 'limit': 50, 'allowed_updates': ['message']}
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
                handled_now += bool(self.handle_message(message))
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
            return self._reply(chat_id, self._profiles_text())
        if looks_like_submission(text):
            return self._submission(chat_id, message, text)
        if command in HELP_COMMANDS or not command:
            return self._reply(chat_id, template_text())
        return self._reply(chat_id, 'Comando no reconocido. Use /plantilla, /provincias, /oficinas o /perfiles.')

    def _reply(self, chat_id, text):
        self.client.send(chat_id, text[:4000])
        return True

    def _profiles_text(self):
        try:
            tasks = self.store.load()
        except ValueError:
            return 'No se pudo leer la lista de perfiles.'
        if not tasks:
            return 'No hay perfiles.'
        return 'Perfiles:\n' + '\n'.join(f'• {t.label} ({t.province})' + (' ⚠ revisar datos' if t.errors else '') for t in tasks)

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
