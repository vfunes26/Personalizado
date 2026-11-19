"""Offline byte-for-byte verification for data transferred between portables.

The verifier never reads, prints or sends the contents of a customer's profile.
It is used only after staging and before replacing an old local compilation.
"""
import argparse
import hashlib
import os
import subprocess
from pathlib import Path


class MigrationError(ValueError):
    pass


def _redirected(path):
    # On Windows, directory junctions are not necessarily reported as symlinks.
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _inventory(root):
    root = Path(root)
    if not root.is_dir() or _redirected(root):
        raise MigrationError('La carpeta de datos no existe o es un enlace.')
    result = {}

    def walk_error(exc):
        # os.walk silently skips unreadable/deep directories without onerror.
        raise MigrationError('No se pudo leer por completo la carpeta privada.') from exc

    for directory, folders, files in os.walk(root, topdown=True, followlinks=False,
                                             onerror=walk_error):
        current = Path(directory)
        if _redirected(current):
            raise MigrationError('Carpeta de datos enlazada.')
        for name in folders:
            if _redirected(current / name):
                raise MigrationError('Carpeta privada enlazada.')
        for name in files:
            item = current / name
            if not item.is_file() or _redirected(item):
                raise MigrationError('Archivo privado enlazado o inaccesible.')
            relative = item.relative_to(root).as_posix()
            with item.open('rb') as stream:
                before = os.fstat(stream.fileno())
                digest = hashlib.file_digest(stream, 'sha256').digest()
                after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise MigrationError('Los archivos privados cambiaron durante la verificación.')
            # WAL/SHM are ordinary Firefox SQLite sidecars. They must be copied
            # together with the database, not removed or silently skipped.
            result[relative] = (after.st_size, digest)
    return result


def verify_migration(source, candidate):
    """Compare all private files exactly; never modify either folder."""
    original = _inventory(source)
    copied = _inventory(candidate)
    if original != copied:
        raise MigrationError('Los archivos privados no coinciden. Compilación cancelada.')
    return len(original)


def copy_migration(source, candidate, *, copier=None):
    """Stage a byte-exact copy without allowing a changing source into a release.

    Keep the pre-copy inventory in memory, avoiding a private manifest on disk.
    The previous portable is never modified by this function.
    """
    before = _inventory(source)
    candidate = Path(candidate)
    if not candidate.is_dir() or _redirected(candidate) or any(candidate.iterdir()):
        raise MigrationError('La carpeta candidata no está vacía o no es segura.')
    if copier is None:
        # Robocopy handles the deep Windows Firefox profile paths and junctions.
        result = subprocess.run([
            'robocopy.exe', str(source), str(candidate), '/E', '/XJ',
            '/R:1', '/W:1', '/NFL', '/NDL', '/NP',
        ], check=False)
        if result.returncode >= 8:
            raise MigrationError('No fue posible copiar los datos privados.')
    else:
        copier(source, candidate)
    after = _inventory(source)
    copied = _inventory(candidate)
    if before != after:
        raise MigrationError('Los datos privados cambiaron durante la copia. Cierra Camoufox antes de repetir.')
    if copied != before:
        raise MigrationError('Los archivos privados no coinciden. Compilación cancelada.')
    return len(before)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--copy', action='store_true',
                        help='Copiar y verificar con una instantánea previa en memoria.')
    args = parser.parse_args()
    try:
        count = (copy_migration(args.source, args.candidate) if args.copy
                 else verify_migration(args.source, args.candidate))
    except (OSError, MigrationError) as exc:
        print('ERROR: No se pudieron verificar los datos privados: ' + str(exc))
        raise SystemExit(1) from None
    print(f'Datos privados conservados: {count} archivos verificados con SHA-256.')
