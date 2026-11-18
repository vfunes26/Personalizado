"""Encrypted, explicitly selected local backup of application state.

No browser profiles, page diagnostics, tokens from the OS credential vault, or
plaintext customer archives are included. No network requests are made.
"""
import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b'CEH-BACKUP-1\x00'
MAX_DATA = 128 * 1024 * 1024
MAX_ARCHIVE = 160 * 1024 * 1024
FILES = frozenset({
    'tasks.yml',
    'data/proxy-profiles.json',
    'data/workers-config.json',
    'data/gmail-settings.json',
    'data/telegram-global.json',
    'data/state.db',
    'data/profile-statistics.sqlite3',
    'data/profile-statistics.json',
    'data/achievements.json',
})
BUDGET = re.compile(r'data/appointment-budget/[a-zA-Z0-9_.-]{1,100}\.json\Z')
DATABASES = frozenset({'data/state.db', 'data/profile-statistics.sqlite3'})


class BackupError(ValueError):
    """Fixed, non-sensitive error explanation."""


def _allowed(name):
    return name in FILES or bool(BUDGET.fullmatch(name))


def _key(password, salt):
    if not isinstance(password, str) or len(password) < 12:
        raise BackupError('La contraseña del respaldo debe tener al menos 12 caracteres.')
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode('utf-8'))


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise BackupError('Ruta de almacenamiento no permitida.')
    fd, temp = tempfile.mkstemp(prefix='.ceh-restore-', dir=path.parent)
    try:
        if hasattr(os, 'fchmod'):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _snapshot_database(path):
    fd, tmp = tempfile.mkstemp(prefix='.ceh-db-', suffix='.sqlite3')
    os.close(fd)
    try:
        with closing(sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True, timeout=5)) as source:
            with closing(sqlite3.connect(tmp)) as destination:
                source.backup(destination)
        return Path(tmp).read_bytes()
    finally:
        Path(tmp).unlink(missing_ok=True)


def _validate_database(data):
    fd, temporary = tempfile.mkstemp(prefix='.ceh-verify-', suffix='.sqlite3')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        with closing(sqlite3.connect(temporary)) as conn:
            if conn.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise BackupError('La base de datos del respaldo no pasa la comprobación de integridad.')
    except sqlite3.Error:
        raise BackupError('La base de datos del respaldo está dañada.') from None
    finally:
        Path(temporary).unlink(missing_ok=True)


def _files(root):
    names = set(FILES)
    budget = root / 'data' / 'appointment-budget'
    if budget.exists() and not budget.is_symlink():
        for p in budget.glob('*.json'):
            names.add(p.relative_to(root).as_posix())
    return sorted(name for name in names if _allowed(name))


def export_backup(root, destination, password):
    """Create a new encrypted archive; never overwrite an existing backup."""
    root, destination = Path(root), Path(destination)
    records = {}
    total = 0
    for name in _files(root):
        source = root / name
        if source.is_symlink() or any(p.is_symlink() for p in source.parents):
            raise BackupError('Se detectó un enlace no permitido en los datos.')
        if not source.is_file():
            continue
        if source.stat().st_size > MAX_DATA:
            raise BackupError('Un archivo supera el límite admitido para respaldos.')
        try:
            data = _snapshot_database(source) if name in DATABASES else source.read_bytes()
        except (OSError, sqlite3.Error):
            raise BackupError('No se pudo leer un archivo de la aplicación.') from None
        total += len(data)
        if total > MAX_DATA:
            raise BackupError('Los datos superan el límite de 128 MB.')
        records[name] = dict(sha256=hashlib.sha256(data).hexdigest(),
                             data=base64.b64encode(data).decode('ascii'))
    if not records:
        raise BackupError('No se encontraron datos para respaldar.')
    inner = json.dumps(dict(format=1, created=datetime.now(timezone.utc).isoformat(),
                            files=records), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    salt, nonce = os.urandom(16), os.urandom(12)
    encrypted = AESGCM(_key(password, salt)).encrypt(nonce, zlib.compress(inner, 6), MAGIC)
    payload = MAGIC + salt + nonce + encrypted
    if len(payload) > MAX_ARCHIVE:
        raise BackupError('El respaldo supera el tamaño admitido.')
    if destination.exists():
        raise BackupError('Ya existe un respaldo con ese nombre. Elige otro archivo.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
        raise BackupError('Ruta de respaldo no permitida.')
    try:
        with destination.open('xb') as stream:
            os.chmod(destination, 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise BackupError('El archivo de respaldo ya existe.') from None
    except OSError:
        destination.unlink(missing_ok=True)
        raise BackupError('No se pudo guardar el respaldo cifrado.') from None
    return len(records)


def _decode(source, password):
    try:
        if source.stat().st_size > MAX_ARCHIVE:
            raise BackupError('El respaldo supera el tamaño admitido.')
        payload = source.read_bytes()
    except OSError:
        raise BackupError('No se pudo leer el respaldo.') from None
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 16 + 12 + 16:
        raise BackupError('Formato de respaldo incompatible o dañado.')
    start = len(MAGIC)
    salt, nonce, encrypted = payload[start:start+16], payload[start+16:start+28], payload[start+28:]
    try:
        packed = AESGCM(_key(password, salt)).decrypt(nonce, encrypted, MAGIC)
    except InvalidTag:
        raise BackupError('Contraseña incorrecta o respaldo alterado.') from None
    inflater = zlib.decompressobj()
    try:
        decoded = inflater.decompress(packed, MAX_DATA * 2 + 1)
        if not inflater.eof or inflater.unconsumed_tail or inflater.unused_data or len(decoded) > MAX_DATA * 2:
            raise BackupError('Contenido comprimido inválido o excesivo.')
        manifest = json.loads(decoded)
    except (zlib.error, UnicodeDecodeError, ValueError, TypeError):
        raise BackupError('El contenido del respaldo está dañado.') from None
    if not isinstance(manifest, dict) or manifest.get('format') != 1 or not isinstance(manifest.get('files'), dict):
        raise BackupError('Formato de respaldo no compatible.')
    records = {}
    total = 0
    for name, entry in manifest['files'].items():
        if not isinstance(name, str) or not _allowed(name) or not isinstance(entry, dict):
            raise BackupError('El respaldo contiene rutas no permitidas.')
        try:
            data = base64.b64decode(entry['data'], validate=True)
        except (KeyError, TypeError, ValueError):
            raise BackupError('Archivo interno inválido.') from None
        total += len(data)
        if total > MAX_DATA or hashlib.sha256(data).hexdigest() != entry.get('sha256'):
            raise BackupError('Integridad de los archivos no verificada.')
        if name in DATABASES:
            if not data.startswith(b'SQLite format 3\x00'):
                raise BackupError('Base de datos del respaldo inválida.')
            _validate_database(data)
        elif name.endswith('.json'):
            try:
                parsed = json.loads(data)
                if not isinstance(parsed, dict):
                    raise ValueError()
            except (ValueError, UnicodeDecodeError):
                raise BackupError('Configuración JSON del respaldo inválida.') from None
        records[name] = data
    if not records or 'tasks.yml' not in records:
        raise BackupError('Respaldo incompleto: faltan los perfiles.')
    return records


def _disable_external_notifications(data):
    """Native Windows/macOS keychain tokens cannot be exported as portable files."""
    import yaml
    try:
        raw = yaml.safe_load(data)
        if not isinstance(raw, dict) or not isinstance(raw.get('tasks', []), list):
            raise ValueError()
        for task in raw['tasks']:
            if not isinstance(task, dict):
                raise ValueError()
            for channel in ('telegram', 'webhook'):
                config = (task.get('notifications') or {}).get(channel)
                if isinstance(config, dict):
                    config['enabled'] = False
                    config['secret_ref'] = ''
        return yaml.safe_dump(raw, allow_unicode=True, sort_keys=False).encode('utf-8')
    except (ValueError, TypeError, yaml.YAMLError, AttributeError):
        raise BackupError('Perfiles del respaldo inválidos.') from None


def restore_backup(root, source, password, *, allow_replace=False):
    """Restore only on explicit consent, with encrypted safety backup and rollback."""
    root = Path(root)
    records = _decode(Path(source), password)
    records['tasks.yml'] = _disable_external_notifications(records['tasks.yml'])
    if 'data/gmail-settings.json' in records:
        # A secret reference from another Windows account is not portable.
        # Keep sender/recipient choices, but require new authentication.
        try:
            gmail = json.loads(records['data/gmail-settings.json'])
            if not isinstance(gmail, dict):
                raise ValueError()
            gmail['secret_ref'] = ''
            records['data/gmail-settings.json'] = json.dumps(
                gmail, ensure_ascii=False, indent=2,
            ).encode('utf-8')
        except (ValueError, TypeError):
            raise BackupError('Configuración de Gmail del respaldo inválida.') from None
    if 'data/telegram-global.json' in records:
        # OS vault entries cannot travel with encrypted backups across accounts.
        # Preserve the administrator and authorized IDs but require a token
        # to be entered again before the global bot can be used.
        try:
            global_telegram = json.loads(records['data/telegram-global.json'])
            if not isinstance(global_telegram, dict):
                raise ValueError()
            global_telegram['secret_ref'] = ''
            global_telegram['enabled'] = False
            records['data/telegram-global.json'] = json.dumps(
                global_telegram, ensure_ascii=False, indent=2,
            ).encode('utf-8')
        except (ValueError, TypeError):
            raise BackupError('Configuración global de Telegram inválida.') from None
    targets = {name: root / name for name in records}
    for path in targets.values():
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise BackupError('La carpeta contiene enlaces no permitidos.')
    current = [name for name, path in targets.items() if path.exists()]
    if current and not allow_replace:
        raise BackupError('Ya hay datos existentes. Se requiere confirmar la sustitución.')
    if current:
        folder = root / 'data' / 'backups'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        export_backup(root, folder / ('antes-de-restaurar-' + stamp + '.cehbackup'), password)
    # Existing SQLite WAL files may replay stale transactions over a newly
    # restored database. Refuse rather than corrupting a running installation.
    for name in records:
        if name in DATABASES:
            path = targets[name]
            if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm')):
                raise BackupError('Cierra la aplicación y consolida las bases SQLite antes de restaurar.')
    original = {name: path.read_bytes() if path.exists() else None for name, path in targets.items()}
    changed = []
    try:
        for name, path in targets.items():
            _atomic_write(path, records[name])
            changed.append(name)
    except (OSError, BackupError):
        for name in reversed(changed):
            try:
                if original[name] is None:
                    targets[name].unlink(missing_ok=True)
                else:
                    _atomic_write(targets[name], original[name])
            except OSError:
                pass
        raise BackupError('Falló la restauración. Se conservó un respaldo previo.') from None
    return len(records)
