"""Produce a small portable manifest and, when possible, a signed-ready delta.

The previous release's tiny manifest is fetched only on an explicit --previous
flag. It never downloads the previous portable/browser and never publishes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.attestations import REPOSITORY
from app.desktop.portable_delta import (
    MAX_MANIFEST, DeltaError, create_delta, delta_asset_name, portable_manifest,
)

API_ROOT = 'https://api.github.com/repos/' + REPOSITORY.removeprefix('https://github.com/')


def previous_release_manifest(version):
    """Optional: fetch only the previous release's small file manifest."""
    req = Request(API_ROOT + '/releases/latest', headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'Cita-Extranjeria-Helper-builder',
    })
    try:
        with urlopen(req, timeout=12) as reply:
            body = reply.read(1024 * 1024 + 1)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if len(body) > 1024 * 1024:
        raise DeltaError('Metadata del release demasiado grande.')
    release = json.loads(body)
    tag = release.get('tag_name')
    if (not isinstance(tag, str) or
            re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag) is None or
            release.get('draft') or release.get('prerelease') or
            release.get('immutable') is not True):
        return None
    previous = tag[1:]
    if (tuple(map(int, previous.split('.'))) >=
            tuple(map(int, version.split('.')))):
        return None
    name = 'portable-manifest-' + previous + '.json'
    expected = REPOSITORY + '/releases/download/' + tag + '/' + name
    assets = [asset for asset in release.get('assets', []) if asset.get('name') == name]
    if len(assets) != 1 or assets[0].get('browser_download_url') != expected:
        return None
    if type(assets[0].get('size')) is not int or not 1 <= assets[0]['size'] <= MAX_MANIFEST:
        raise DeltaError('Manifiesto de versión anterior demasiado grande.')
    with urlopen(Request(expected, headers={
            'User-Agent':'Cita-Extranjeria-Helper-builder',
            'Accept':'application/octet-stream'}),timeout=15) as reply:
        raw = reply.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise DeltaError('Manifiesto de versión anterior demasiado grande.')
    return previous, json.loads(raw)


def build(new_zip, version, *, previous=None, find_previous=False):
    new_zip = Path(new_zip)
    if not new_zip.is_file():
        raise DeltaError('No se encontró el ZIP portable.')
    manifest = portable_manifest(new_zip, version)
    manifest_path = new_zip.parent / ('portable-manifest-' + version + '.json')
    if manifest_path.exists():
        raise DeltaError('El manifiesto ya existe. No se sobrescribió.')
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False,
                                       sort_keys=True, separators=(',', ':')),
                             encoding='utf-8')
    with manifest_path.open('rb') as stream:
        digest = hashlib.file_digest(stream,'sha256').hexdigest()
    manifest_path.with_name(manifest_path.name + '.sha256').write_text(
        digest + '  ' + manifest_path.name + '\n', encoding='utf-8')
    print('Manifiesto:', manifest_path)
    if find_previous:
        try:
            previous = previous_release_manifest(version)
        except (OSError, ValueError):
            # Connectivity issues fetching a tiny optional old manifest
            # cannot block publication of the signed full ZIP.
            previous = None
    if previous is None:
        print('Sin manifiesto anterior disponible: se conserva la actualización completa.')
        return manifest_path, None
    from_version, old_files = previous
    name = delta_asset_name(new_zip.name, from_version)
    output = new_zip.parent / name
    try:
        create_delta(new_zip, old_files, from_version, version, output)
    except DeltaError:
        print('Diferencial no disponible: se conserva la actualización completa.')
        return manifest_path, None
    if output.stat().st_size >= new_zip.stat().st_size:
        output.unlink()
        print('El diferencial no ahorra datos: se conserva el paquete completo.')
        return manifest_path, None
    with output.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    output.with_name(output.name + '.sha256').write_text(
        digest + '  ' + output.name + '\n', encoding='utf-8')
    print('Diferencial:', output, 'bytes:', output.stat().st_size)
    return manifest_path, output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--new-zip', required=True, type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--previous-manifest', type=Path)
    parser.add_argument('--from-version')
    parser.add_argument('--find-previous', action='store_true')
    args = parser.parse_args()
    if args.find_previous and args.previous_manifest:
        parser.error('Usa un único origen de manifiesto anterior.')
    if bool(args.previous_manifest) != bool(args.from_version):
        if not args.find_previous:
            parser.error('Se necesitan --previous-manifest y --from-version juntos.')
    prev = ((args.from_version, args.previous_manifest)
            if args.previous_manifest else None)
    build(args.new_zip, args.version, previous=prev, find_previous=args.find_previous)
