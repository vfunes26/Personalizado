"""Global Telegram owner and delegated chat permissions.

The bot token is stored exclusively in the native OS credential vault.
The local JSON contains only a secret reference and authorized chat IDs.
"""
import json
import os
from pathlib import Path
import re
import tempfile

from .notification_store import NotificationVault
from ..locking import ensure_private_path, locked_file
from ..notifications import NotificationError, Telegram


class TelegramGlobalError(ValueError):
    """Non-sensitive configuration error."""


def valid_private_id(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value) is not None


class TelegramGlobalStore:
    def __init__(self, root, vault=None):
        self.path = Path(root) / 'data' / 'telegram-global.json'
        self.vault = vault if vault is not None else NotificationVault()

    def _check_private_path(self):
        try:
            ensure_private_path(self.path)
        except OSError:
            raise TelegramGlobalError('La ruta de Telegram no puede ser un enlace.') from None

    def load(self):
        self._check_private_path()
        if not self.path.exists():
            return dict(owner_chat_id='', authorized_chat_ids=[], secret_ref='', enabled=False)
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise TelegramGlobalError('No se pudo leer la configuración global de Telegram.') from None
        if not isinstance(value, dict):
            raise TelegramGlobalError('Formato inválido de la configuración de Telegram.')
        owner = value.get('owner_chat_id', '')
        authorized = value.get('authorized_chat_ids', [])
        ref = value.get('secret_ref', '')
        if (not isinstance(owner, str) or (owner and not valid_private_id(owner))
                or not isinstance(authorized, list) or len(authorized) > 30
                or any(not valid_private_id(x) for x in authorized)
                or len(authorized) != len(set(authorized)) or owner in authorized
                or not isinstance(ref, str)):
            raise TelegramGlobalError('IDs o referencia de Telegram inválidos.')
        return dict(owner_chat_id=owner, authorized_chat_ids=list(dict.fromkeys(authorized)),
                    secret_ref=ref, enabled=bool(value.get('enabled', False)))

    def validate(self, owner_chat_id, authorized_chat_ids, token=''):
        """Preflight permissions and bot credentials without changing files or threads."""
        owner = str(owner_chat_id).strip()
        try:
            others = [str(x).strip() for x in authorized_chat_ids]
        except TypeError:
            raise TelegramGlobalError('Lista de ID autorizados inválida.') from None
        if not valid_private_id(owner):
            raise TelegramGlobalError('Introduce el Chat ID privado principal, solo números.')
        if (len(others) > 30 or any(not valid_private_id(x) for x in others)
                or len(set(others)) != len(others) or owner in others):
            raise TelegramGlobalError('Los ID autorizados deben ser privados, únicos y distintos del principal.')
        if token:
            try:
                Telegram(token)
            except (NotificationError, ValueError, TypeError):
                raise TelegramGlobalError('Formato del token de Telegram inválido.') from None
        elif not self.load()['secret_ref']:
            raise TelegramGlobalError('Introduce el token del bot para activar Telegram global.')
        return owner, others

    def save(self, owner_chat_id, authorized_chat_ids, token=''):
        owner, others = self.validate(owner_chat_id, authorized_chat_ids, token)
        self._check_private_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_private_path()
        with locked_file(self.path.with_name('.telegram-global.lock')):
            previous = self.load()
            reference = previous['secret_ref']
            created = ''
            if token:
                try:
                    Telegram(token)
                    created = self.vault.put({'token': token})
                    if self.vault.get(created).get('token') != token:
                        raise NotificationError('Error al verificar el token guardado.')
                    reference = created
                except Exception:
                    if created:
                        try:
                            self.vault.delete(created)
                        except Exception:
                            pass
                    raise TelegramGlobalError('No se pudo guardar el token de forma segura.') from None
            elif not reference:
                raise TelegramGlobalError('Introduce el token del bot para activar Telegram global.')
            data = dict(version=1, enabled=True, owner_chat_id=owner,
                        authorized_chat_ids=others, secret_ref=reference)
            fd, temporary = tempfile.mkstemp(prefix='.telegram-global-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    json.dump(data, output, ensure_ascii=False, indent=2)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
            except OSError:
                if created:
                    self.vault.delete(created)
                raise TelegramGlobalError('No se pudo actualizar Telegram. La configuración anterior se conserva.') from None
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            # Keep previous credential entries for possible encrypted backups.
            return data

    def credentials(self):
        data = self.load()
        if not data['enabled'] or not data['owner_chat_id'] or not data['secret_ref']:
            return None
        try:
            token = self.vault.get(data['secret_ref']).get('token', '')
            Telegram(token)
        except Exception:
            raise TelegramGlobalError('El token global no está disponible en este equipo.') from None
        return dict(data, token=token)
