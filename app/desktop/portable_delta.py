"""Verified Windows portable file-level delta packages.

This module never modifies the source portable or copies its private data.
A delta MUST first be verified with updates.verify_download (SHA-256 + Sigstore).
Only a signed delta's complete file manifest can authorize staged output.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

ZIP_ROOT = 'Cita Extranjeria Helper/'
MANIFEST = 'portable-delta.json'
FORMAT = 'ceh-portable-delta-v1'
FILE_FORMAT = 'ceh-portable-files-v1'
MAX_FILES = 20000
MAX_MANIFEST = 8 * 1024 * 1024
MAX_TOTAL = 2 * 1024 ** 3
HASH = re.compile(r'[0-9a-f]{64}\Z')
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+\Z')
RESERVED = re.compile(r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z')


class DeltaError(ValueError):
    """Untrusted or invalid delta content; never install."""


class DeltaIncompatible(DeltaError):
    """Source portable does not match the signed base-file requirements."""


def _path(value):
    if (not isinstance(value, str) or not value or len(value) > 480 or
            value.startswith('/') or '\\' in value or ':' in value or
            any(char in value for char in '<>"|?*') or
            any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise DeltaError('Ruta no permitida en el paquete diferencial.')
    path = PurePosixPath(value)
    if (str(path) != value or any(part in {'.', '..', ''} or
            part.endswith(('.', ' ')) or RESERVED.fullmatch(part)
            for part in value.split('/'))):
        raise DeltaError('Ruta no permitida en el paquete diferencial.')
    lower = value.casefold()
    if lower in {'tasks.yml', 'data'} or lower.startswith('data/'):
        raise DeltaError('Un paquete diferencial no puede contener datos privados.')
    return path


def _hash_stream(stream):
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_TOTAL:
            raise DeltaError('Archivo demasiado grande.')
        digest.update(chunk)
    return digest.hexdigest(), size


def _zip_entries(archive, *, prefix):
    entries = {}
    names = set()
    for info in archive.infolist():
        if info.is_dir():
            if (info.filename == ZIP_ROOT + 'data/' and prefix == ZIP_ROOT) or (
                    info.filename == 'files/' and prefix == 'files/'):
                continue
            if prefix == ZIP_ROOT and info.filename == ZIP_ROOT:
                continue
            raise DeltaError('Directorio inesperado en el archivo.')
        if (info.flag_bits & 1 or (info.external_attr >> 16) & 0o170000 == 0o120000
                or not info.filename.startswith(prefix)):
            raise DeltaError('Archivo inválido o enlace simbólico.')
        name = info.filename[len(prefix):]
        _path(name)
        folded = name.casefold()
        if folded in names or info.file_size > MAX_TOTAL:
            raise DeltaError('Archivo duplicado o demasiado grande.')
        names.add(folded)
        entries[name] = info
        if len(entries) > MAX_FILES:
            raise DeltaError('Demasiados archivos.')
    return entries


def portable_manifest(archive_path, version):
    """Hash all installed files in a full Windows portable ZIP (local build)."""
    if not VERSION.fullmatch(version):
        raise DeltaError('Versión inválida.')
    result = {}
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        entries = _zip_entries(archive, prefix=ZIP_ROOT)
        for name, info in sorted(entries.items()):
            with archive.open(info) as stream:
                digest, size = _hash_stream(stream)
            if size != info.file_size:
                raise DeltaError('Tamaño incorrecto en el paquete original.')
            total += size
            if total > MAX_TOTAL:
                raise DeltaError('El paquete excede el límite.')
            result[name] = {'sha256': digest, 'size': size}
    if 'portable.flag' not in result:
        raise DeltaError('No es una distribución portable.')
    return {'format': FILE_FORMAT, 'version': version, 'files': result}


def _load_previous(previous, from_version):
    if isinstance(previous, (str, Path)):
        previous = json.loads(Path(previous).read_text(encoding='utf-8'))
    if not isinstance(previous, dict) or previous.get('format') != FILE_FORMAT or (
            previous.get('version') != from_version) or not isinstance(previous.get('files'), dict):
        raise DeltaError('Manifiesto de versión anterior incompatible.')
    files = previous['files']
    if len(files) > MAX_FILES:
        raise DeltaError('Manifiesto anterior demasiado grande.')
    seen = set()
    for name, entry in files.items():
        _path(name)
        if name.casefold() in seen:
            raise DeltaError('Archivos duplicados.')
        seen.add(name.casefold())
        if (not isinstance(entry, dict) or
                not HASH.fullmatch(str(entry.get('sha256', ''))) or
                type(entry.get('size')) is not int or
                not 0 <= entry['size'] <= MAX_TOTAL):
            raise DeltaError('Manifiesto anterior inválido.')
    return files


def delta_asset_name(full_portable_name, from_version):
    if (not VERSION.fullmatch(from_version) or
            not re.fullmatch(r'[A-Za-z0-9_.-]+-portable\.zip', full_portable_name)):
        raise DeltaError('Nombre de paquete diferencial inválido.')
    return full_portable_name[:-4] + '-from-' + from_version + '.delta.zip'


def create_delta(new_zip, old_manifest, from_version, to_version, destination):
    """Create a local delta from a full new ZIP and a small old-file manifest."""
    if (not VERSION.fullmatch(from_version) or not VERSION.fullmatch(to_version) or
            tuple(map(int, to_version.split('.'))) <= tuple(map(int, from_version.split('.')))):
        raise DeltaError('Las versiones no son compatibles.')
    base = _load_previous(old_manifest, from_version)
    current = portable_manifest(new_zip, to_version)
    files = {}
    for name, new in current['files'].items():
        old = base.get(name)
        action = 'reuse' if old == new else 'replace'
        files[name] = {**new, 'action': action}
    statement = {'format': FORMAT, 'from_version': from_version,
                 'to_version': to_version, 'files': files}
    encoded = json.dumps(statement, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_MANIFEST:
        raise DeltaError('Manifiesto diferencial demasiado grande.')
    destination = Path(destination)
    if destination.exists():
        raise DeltaError('No se sobrescriben paquetes existentes.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.new-delta-', suffix='.zip', dir=destination.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(new_zip) as original, zipfile.ZipFile(
                temp, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as output:
            entries = {name: info for name, info in _zip_entries(original, prefix=ZIP_ROOT).items()}
            output.writestr(MANIFEST, encoded)
            for name, entry in files.items():
                if entry['action'] == 'replace':
                    with original.open(entries[name]) as source, output.open('files/' + name, 'w') as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
        os.replace(temp, destination)
        return destination
    finally:
        Path(temp).unlink(missing_ok=True)


def _delta_manifest(archive, from_version, to_version):
    names = archive.namelist()
    if names.count(MANIFEST) != 1:
        raise DeltaError('Falta el manifiesto firmado del diferencial.')
    info = archive.getinfo(MANIFEST)
    if info.file_size > MAX_MANIFEST:
        raise DeltaError('Manifiesto diferencial demasiado grande.')
    with archive.open(info) as source:
        raw = source.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise DeltaError('Manifiesto diferencial demasiado grande.')
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise DeltaError('Claves duplicadas en el manifiesto.')
            result[name] = value
        return result
    try:
        obj = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeDecodeError, ValueError) as exc:
        raise DeltaError('Manifiesto diferencial inválido.') from exc
    if (not isinstance(obj, dict) or set(obj) !=
            {'format', 'from_version', 'to_version', 'files'} or
            obj['format'] != FORMAT or obj['from_version'] != from_version or
            obj['to_version'] != to_version or not isinstance(obj['files'], dict)):
        raise DeltaError('Versión diferencial inesperada.')
    files = obj['files']
    if len(files) > MAX_FILES or 'portable.flag' not in files:
        raise DeltaError('Contenido diferencial incompleto.')
    seen = set()
    changed = set()
    total = 0
    for name, entry in files.items():
        _path(name)
        if name.casefold() in seen:
            raise DeltaError('Archivos duplicados en el manifiesto.')
        seen.add(name.casefold())
        if (not isinstance(entry, dict) or set(entry) != {'action', 'sha256', 'size'}
                or entry['action'] not in {'reuse', 'replace'}
                or not isinstance(entry['sha256'], str) or not HASH.fullmatch(entry['sha256'])
                or type(entry['size']) is not int or not 0 <= entry['size'] <= MAX_TOTAL):
            raise DeltaError('Contenido diferencial inválido.')
        total += entry['size']
        if total > MAX_TOTAL:
            raise DeltaError('Tamaño del portable excedido.')
        if entry['action'] == 'replace':
            changed.add(name)
    payload_names = set()
    for member in archive.infolist():
        if member.filename == MANIFEST:
            continue
        if member.is_dir() or (member.flag_bits & 1) or (
                (member.external_attr >> 16) & 0o170000 == 0o120000):
            raise DeltaError('Entrada ZIP no permitida.')
        if not member.filename.startswith('files/'):
            raise DeltaError('Archivo inesperado en paquete diferencial.')
        name = member.filename[len('files/'):]
        _path(name)
        if name in payload_names or name not in changed or member.file_size != files[name]['size']:
            raise DeltaError('Archivo de reemplazo inesperado.')
        payload_names.add(name)
    if payload_names != changed:
        raise DeltaError('Faltan archivos cambiados.')
    return files


def _safe_source(source_root, name):
    path = source_root.joinpath(*PurePosixPath(name).parts)
    if not path.is_file() or path.is_symlink():
        raise DeltaIncompatible('El archivo original no existe o no es seguro.')
    if any(parent.is_symlink() for parent in path.parents if parent != source_root.parent):
        raise DeltaIncompatible('La carpeta del portable original contiene enlaces.')
    return path


def check_delta_base(source_root, delta_zip, from_version, to_version):
    """Verify only reused bytes before accepting a delta instead of a full ZIP."""
    source_root = Path(source_root)
    if (not (source_root / 'portable.flag').is_file() or
            not VERSION.fullmatch(from_version) or not VERSION.fullmatch(to_version)):
        raise DeltaIncompatible('El portable original no corresponde a la actualización.')
    with zipfile.ZipFile(delta_zip) as archive:
        files = _delta_manifest(archive, from_version, to_version)
        for name, entry in files.items():
            if entry['action'] != 'reuse':
                continue
            path = _safe_source(source_root, name)
            if path.stat().st_size != entry['size']:
                raise DeltaIncompatible('Los archivos originales cambiaron.')
            with path.open('rb') as stream:
                digest, size = _hash_stream(stream)
            if digest != entry['sha256'] or size != entry['size']:
                raise DeltaIncompatible('Los archivos originales cambiaron.')
    return True


def stage_delta(source_root, delta_zip, from_version, to_version, *, verifier=None):
    """Prepare an independent executable-only folder beside the old portable.

    The signed ZIP is re-verified before staging. No private data is copied.
    The original folder is never overwritten, even if verification fails.
    """
    from .updates import verify_download
    source_root = Path(source_root)
    delta_zip = Path(delta_zip)
    (verifier or verify_download)(delta_zip)
    check_delta_base(source_root, delta_zip, from_version, to_version)
    parent = source_root.parent
    candidate = parent / ('Cita Extranjeria Helper - ' + to_version + ' (preparado)')
    if candidate.exists() or candidate.is_symlink() or parent.is_symlink():
        raise DeltaError('La carpeta de actualización ya existe. No se sobrescribió nada.')
    temp = Path(tempfile.mkdtemp(prefix='.ceh-next-', dir=parent))
    try:
        with zipfile.ZipFile(delta_zip) as archive:
            files = _delta_manifest(archive, from_version, to_version)
            for name, entry in files.items():
                target = temp.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if entry['action'] == 'reuse':
                    with _safe_source(source_root, name).open('rb') as stream, target.open('wb') as out:
                        digest = hashlib.sha256()
                        size = 0
                        while chunk := stream.read(1024 * 1024):
                            size += len(chunk)
                            if size > entry['size']:
                                raise DeltaIncompatible('El portable original cambió durante la copia.')
                            digest.update(chunk)
                            out.write(chunk)
                else:
                    with archive.open('files/' + name) as stream, target.open('wb') as out:
                        digest = hashlib.sha256()
                        size = 0
                        while chunk := stream.read(1024 * 1024):
                            size += len(chunk)
                            if size > entry['size']:
                                raise DeltaError('Archivo diferencial demasiado grande.')
                            digest.update(chunk)
                            out.write(chunk)
                if digest.hexdigest() != entry['sha256'] or size != entry['size']:
                    raise DeltaError('Un archivo no coincide con la firma del paquete.')
        (temp / 'data').mkdir(exist_ok=True)
        temp.rename(candidate)
        return candidate
    finally:
        if temp.exists():
            shutil.rmtree(temp)
