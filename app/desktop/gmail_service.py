"""Opt-in Gmail SMTP delivery. Credentials remain in the OS credential vault."""
from email.message import EmailMessage
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import tempfile

from .notification_store import NotificationVault
from ..locking import ensure_private_path
from ..notifications import NotificationError

SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 465
ADDRESS = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}$")
MAX_RECIPIENTS = 10


class GmailError(NotificationError):
    """Safe diagnostic: never forward SMTP exceptions or credentials."""


def _address(value):
    value = str(value or '').strip().lower()
    if len(value) > 254 or not ADDRESS.fullmatch(value) or '..' in value:
        raise GmailError('Introduce una dirección de correo válida.')
    return value


def parse_recipients(value):
    if isinstance(value, str):
        entries = re.split(r'[,;\n]+', value)
    elif isinstance(value, (tuple, list)):
        entries = value
    else:
        raise GmailError('Lista de destinatarios inválida.')
    entries = [str(entry).strip() for entry in entries if str(entry).strip()]
    recipients = tuple(dict.fromkeys(_address(entry) for entry in entries))
    if not recipients or len(recipients) > MAX_RECIPIENTS:
        raise GmailError('Configura entre 1 y 10 destinatarios autorizados.')
    return recipients


class GmailSettings:
    def __init__(self, path, vault=None, smtp_factory=None):
        self.path = Path(path)
        self.vault = vault if vault is not None else NotificationVault()
        self.smtp_factory = smtp_factory or smtplib.SMTP_SSL

    def _guard_path(self):
        try:
            ensure_private_path(self.path)
        except OSError:
            raise GmailError('La ruta de configuración de Gmail no está permitida.') from None

    def read(self):
        self._guard_path()
        if not self.path.exists():
            return {'sender': '', 'recipients': [], 'secret_ref': ''}
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict) or set(raw) - {'sender', 'recipients', 'secret_ref'}:
                raise ValueError()
            sender = _address(raw.get('sender', ''))
            recipients = list(parse_recipients(raw.get('recipients', [])))
            ref = raw.get('secret_ref', '')
            if not isinstance(ref, str) or (ref and not re.fullmatch(r'notifications-[a-f0-9]{32}', ref)):
                raise ValueError()
            return {'sender': sender, 'recipients': recipients, 'secret_ref': ref}
        except (OSError, ValueError, TypeError, GmailError):
            raise GmailError('No se pudo leer la configuración de Gmail.') from None

    def save(self, sender, recipients, app_password=None):
        """Save metadata atomically; replace keychain secret only when supplied."""
        sender = _address(sender)
        addresses = list(parse_recipients(recipients))
        self._guard_path()
        old = self.read()
        change_sender = bool(old['sender'] and old['sender'] != sender)
        if change_sender and not app_password:
            raise GmailError('Al cambiar la cuenta debes introducir otra contraseña de aplicación.')
        ref = old['secret_ref']
        created = ''
        if app_password:
            if not isinstance(app_password, str) or not 8 <= len(app_password.replace(' ', '')) <= 128:
                raise GmailError('Introduce una contraseña de aplicación de Gmail válida.')
            try:
                created = self.vault.put({'gmail_app_password': app_password.replace(' ', '')})
            except Exception:
                raise GmailError('No se pudo guardar la contraseña en el almacén seguro.') from None
            ref = created
        if not ref:
            raise GmailError('Introduce la contraseña de aplicación para configurar Gmail.')
        data = {'sender': sender, 'recipients': addresses, 'secret_ref': ref}
        temp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._guard_path()
            fd, temp = tempfile.mkstemp(prefix='.gmail-settings-', dir=self.path.parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        except (OSError, GmailError) as exc:
            if created:
                self.vault.delete(created)
            if isinstance(exc, GmailError):
                raise
            raise GmailError('No se pudo guardar la configuración de Gmail.') from None
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)
        if created and old['secret_ref'] and old['secret_ref'] != created:
            self.vault.delete(old['secret_ref'])
        return data

    def send(self, subject, body, recipients=None):
        """Send only to addresses already approved in saved configuration."""
        data = self.read()
        if not data['secret_ref'] or not data['sender']:
            raise GmailError('Configura Gmail antes de enviar correos.')
        addresses = list(parse_recipients(recipients if recipients is not None else data['recipients']))
        if not set(addresses).issubset(set(data['recipients'])):
            raise GmailError('El destinatario no está autorizado en la configuración.')
        if not isinstance(subject, str) or not 1 <= len(subject) <= 160 or '\r' in subject or '\n' in subject:
            raise GmailError('Asunto inválido.')
        if not isinstance(body, str) or not 1 <= len(body) <= 100000:
            raise GmailError('Contenido de correo inválido.')
        try:
            private = self.vault.get(data['secret_ref'])
            password = private['gmail_app_password']
            if not isinstance(password, str) or not password:
                raise ValueError()
        except Exception:
            raise GmailError('La contraseña de Gmail no está disponible en el almacén seguro.') from None
        message = EmailMessage()
        message['From'] = data['sender']
        message['To'] = ', '.join(addresses)
        message['Subject'] = subject
        message.set_content(body)
        try:
            with self.smtp_factory(SMTP_HOST, SMTP_PORT, timeout=20,
                                   context=ssl.create_default_context()) as smtp:
                smtp.login(data['sender'], password)
                smtp.send_message(message, from_addr=data['sender'], to_addrs=addresses)
        except (smtplib.SMTPException, OSError, TimeoutError, ssl.SSLError, ValueError):
            raise GmailError('No se pudo entregar el correo. Comprueba conexión, cuenta y contraseña de aplicación.') from None
        return len(addresses)

    def test(self):
        data = self.read()
        if not data['recipients']:
            raise GmailError('Configura al menos un destinatario antes de probar Gmail.')
        return self.send('Prueba de Cita Extranjería Helper',
                         'Esta es una prueba de configuración de Gmail. No contiene datos personales.',
                         recipients=[data['recipients'][0]])
