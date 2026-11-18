"""Guarded profile deletion with an auditable local record and Gmail receipt.

This module never modifies profile creation, browser automation or Telegram
pairing. Audit events contain internal IDs only, never applicant data.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from ..config import TIE_PROCEDURE, REGRESO_PROCEDURE
from ..notifications import NotificationError
from ..state import StateStore
from .gmail_service import GmailError, GmailSettings
from .profiles import ProfileConflictError, ProfileValidationError
from .proxy_profiles import ProxyProfileStore


class ProfileDeletionError(NotificationError):
    pass


def profile_receipt(raw, profile_id):
    """Complete applicant/request fields, excluding notifications and secrets."""
    request = raw.get('request') or {}
    applicant = raw.get('applicant') or {}
    contact = applicant.get('contact') or {}
    procedure = request.get('procedure', '')
    procedure = ('TIE — toma de huellas' if procedure == TIE_PROCEDURE else
                 'Autorización de regreso' if procedure == REGRESO_PROCEDURE else
                 str(procedure or ''))
    rows = [
        ('Identificador', profile_id),
        ('Nombre del perfil', raw.get('label', '')),
        ('Trámite', procedure),
        ('Provincia', request.get('province', '')),
        ('Oficina', request.get('office') or 'Cualquiera'),
        ('Acceso', request.get('access_mode', '')),
        ('Método Cl@ve', request.get('clave_method', '')),
        ('Subtrámite', request.get('subprocedure') or ''),
        ('Comportamiento sin citas', request.get('no_slots_mode', '')),
        ('Espera del solicitante', request.get('applicant_no_slots_mode', '')),
        ('Relleno de formulario', applicant.get('fill_mode', '')),
        ('Documento', applicant.get('document_type', '')),
        ('Número de documento', applicant.get('document_number', '')),
        ('Nombre completo', applicant.get('full_name', '')),
        ('Nacionalidad', applicant.get('nationality', '')),
        ('Teléfono', contact.get('phone', '')),
        ('Correo', contact.get('email', '')),
    ]
    protection = request.get('appointment_protection')
    if isinstance(protection, dict):
        # Profile request settings, not browser sessions or notification secrets.
        rows.append(('Protección de citas', json.dumps(protection, ensure_ascii=False, sort_keys=True, default=str)))
    timings = raw.get('timings')
    if isinstance(timings, dict):
        rows.append(('Temporizadores', json.dumps(timings, ensure_ascii=False, sort_keys=True, default=str)))
    return '\n'.join(f'{title}: {str(value)}' for title, value in rows)


def _atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.delete-profile-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ProfileDeletionService:
    def __init__(self, store, *, mail=None, vault=None, busy_checker=None):
        self.store = store
        self.root = Path(store.path).parent
        self.mail = mail if mail is not None else GmailSettings(self.root / 'data' / 'gmail-settings.json')
        self.vault = vault
        self.busy_checker = busy_checker or (lambda _profile_id: False)

    def _audit(self, profile_id, origin, event):
        path = self.root / 'data' / 'profile-deletions.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ProfileDeletionError('La ruta de auditoría no es segura.')
        record = {
            'time_utc': datetime.now(timezone.utc).isoformat(),
            'profile_id': str(profile_id), 'origin': origin, 'event': event,
        }
        with path.open('a', encoding='utf-8') as stream:
            if os.name != 'nt':
                os.chmod(path, 0o600)
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def _cleanup_bindings(self, profile_id):
        """Best effort: never erase a different profile's proxy or worker."""
        warnings = []
        proxy_path = self.root / 'data' / 'proxy-profiles.json'
        if proxy_path.exists():
            try:
                ProxyProfileStore(proxy_path).unbind_request_profile(profile_id)
            except (OSError, ValueError):
                warnings.append('proxy')
        worker_path = self.root / 'data' / 'workers-config.json'
        if worker_path.exists():
            try:
                raw = json.loads(worker_path.read_text(encoding='utf-8'))
                if not isinstance(raw, dict) or not isinstance(raw.get('rows'), list):
                    raise ValueError()
                altered = False
                for row in raw['rows']:
                    if isinstance(row, dict) and row.get('profile_id') == profile_id:
                        row.update(active=False, profile_id=None, proxy_id=None)
                        altered = True
                if altered:
                    _atomic_json(worker_path, raw)
            except (OSError, ValueError, TypeError):
                warnings.append('trabajadores')
        return warnings

    def _release_secret(self, deleted):
        if self.vault is None:
            return
        conf = (deleted.get('notifications') or {}).get('telegram') or {}
        ref = conf.get('secret_ref')
        if not ref:
            return
        try:
            for task in self.store._read().get('tasks', []):
                for channel in ('telegram', 'webhook'):
                    if ((task.get('notifications') or {}).get(channel) or {}).get('secret_ref') == ref:
                        return
            self.vault.delete(ref)
        except (OSError, ValueError, NotificationError):
            pass  # Keep a harmless orphan rather than deleting a shared key.

    def delete(self, profile_id, *, revision, origin, protected_profile_id=None):
        if origin not in {'telegram', 'interfaz'}:
            raise ProfileDeletionError('Origen no autorizado.')
        if not profile_id or profile_id == protected_profile_id:
            raise ProfileDeletionError('No se puede eliminar el perfil que mantiene conectado el bot.')
        try:
            config = self.mail.read()
            if not config.get('secret_ref') or not config.get('recipients'):
                raise ProfileDeletionError('Configura Gmail y sus destinatarios antes de eliminar perfiles.')
            if self.busy_checker(profile_id):
                raise ProfileDeletionError('El perfil está iniciando o ejecutándose. Deténlo primero.')
            with StateStore(self.root / 'data' / 'state.db').task_lock(profile_id) as acquired:
                if not acquired or self.busy_checker(profile_id):
                    raise ProfileDeletionError('El perfil está en ejecución. Deténlo primero.')
                # Reject changed lists, including renamed or reordered profiles.
                if self.store.revision() != revision:
                    raise ProfileDeletionError('La lista cambió. Consulta los perfiles otra vez.')
                self._audit(profile_id, origin, 'confirmed')
                deleted = self.store.delete_profile(profile_id, revision=revision)
        except (ProfileConflictError, ProfileValidationError):
            raise ProfileDeletionError('El perfil cambió. Actualiza la lista y vuelve a confirmar.') from None
        except (OSError, ValueError) as exc:
            if isinstance(exc, ProfileDeletionError):
                raise
            raise ProfileDeletionError('No se pudo eliminar el perfil con seguridad.') from None
        warnings = self._cleanup_bindings(profile_id)
        self._release_secret(deleted)
        try:
            self._audit(profile_id, origin, 'deleted')
        except (OSError, ProfileDeletionError):
            # The profile is already gone. Return truthful success with a
            # warning instead of telling the user that deletion failed.
            warnings.append('auditoría')
        subject = 'Cita Extranjería Helper — perfil eliminado'
        message = ('Se confirmó la eliminación desde ' + origin + '.\n'
                   'Fecha UTC: ' + datetime.now(timezone.utc).isoformat() + '\n\n'
                   + profile_receipt(deleted, profile_id)
                   + '\n\nEl perfil fue eliminado de la lista de la aplicación.')
        try:
            self.mail.send(subject, message)
        except (GmailError, NotificationError, OSError):
            try:
                self._audit(profile_id, origin, 'gmail_failed')
            except (OSError, ProfileDeletionError):
                warnings.append('auditoría')
            return {'deleted': True, 'emailed': False, 'warnings': warnings}
        try:
            self._audit(profile_id, origin, 'gmail_sent')
        except (OSError, ProfileDeletionError):
            warnings.append('auditoría')
        return {'deleted': True, 'emailed': True, 'warnings': warnings}
