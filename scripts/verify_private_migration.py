"""Offline byte-for-byte verification for data transferred between portables.

The verifier never reads, prints or sends the contents of a customer's profile.
It is used only after staging and before replacing an old local compilation.
"""
import argparse
import hashlib
import os
from pathlib import Path


class MigrationError(ValueError):
    pass


def _inventory(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise MigrationError('La carpeta de datos no existe o es un enlace.')
    result = {}
    for directory, folders, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        if current.is_symlink():
            raise MigrationError('Carpeta de datos enlazada.')
        for name in folders:
            item = current / name
            if item.is_symlink():
                raise MigrationError('Carpeta privada enlazada.')
        for name in files:
            item = current / name
            if not item.is_file() or item.is_symlink():
                raise MigrationError('Archivo privado enlazado o inaccesible.')
            if item.name.lower().endswith(('-wal', '-shm')):
                # A running/crashed database needs recovery with its own
                # SQLite engine before it is safe to copy.
                raise MigrationError('Hay una base SQLite activa o pendiente de recuperación.')
            relative = item.relative_to(root).as_posix()
            with item.open('rb') as stream:
                result[relative] = (
                    item.stat().st_size, hashlib.file_digest(stream, 'sha256').digest())
    return result


def verify_migration(source, candidate):
    """Compare all private files exactly; never modify either folder."""
    original = _inventory(source)
    copied = _inventory(candidate)
    if original != copied:
        raise MigrationError('Los archivos privados no coinciden. Compilación cancelada.')
    return len(original)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    try:
        count = verify_migration(args.source, args.candidate)
    except (OSError, MigrationError) as exc:
        print('ERROR: No se pudieron verificar los datos privados: ' + str(exc))
        raise SystemExit(1) from None
    print(f'Datos privados conservados: {count} archivos verificados con SHA-256.')
